"""Durable, bounded Salesforce delivery; historical reads confer no write authority."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

from .contracts import canonical, digest
from .salesforce_contract import DeliveryError
from .store import Refused

TERMINAL = {"delivered", "blocked", "exhausted"}


class SalesforceDispatcher:
    def __init__(self, workbench, inbox, journal, *, max_attempts=4, ttl=3600, clock=time.time):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 8 or not 30 <= ttl <= 3600:
            raise ValueError("bounded_retry_policy_required")
        self.bench, self.inbox, self.path = workbench, inbox, Path(journal)
        if self.path.resolve() == workbench.store.path.resolve():
            raise ValueError("separate_durable_journal_required")
        self.max_attempts, self.ttl, self.clock = max_attempts, ttl, clock
        self.journal_pin = digest({"destination": inbox.destination_pin, "max_attempts": max_attempts, "ttl": ttl})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal() as c:
            c.executescript("""
              CREATE TABLE IF NOT EXISTS deliveries(
                key TEXT PRIMARY KEY, pin TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL,
                first_at REAL NOT NULL, next_at REAL NOT NULL, detail TEXT NOT NULL, receipt TEXT);
              CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, key TEXT NOT NULL,
                at REAL NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT,'append only'); END;
              CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT,'append only'); END;
            """)

    @contextmanager
    def journal(self):
        with sqlite3.connect(self.path, timeout=30) as c:
            c.row_factory = sqlite3.Row
            yield c

    def status(self, key):
        with self.journal() as c:
            row = c.execute("SELECT * FROM deliveries WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def _mark(self, key, state, detail, *, next_at=0, receipt=None):
        with self.journal() as c:
            c.execute("UPDATE deliveries SET state=?,detail=?,next_at=?,receipt=? WHERE key=?",
                      (state, detail, next_at, canonical(receipt) if receipt else None, key))
            c.execute("INSERT INTO events(key,at,state,detail) VALUES(?,?,?,?)",
                      (key, self.clock(), state, detail))
        return self.status(key)

    def _approved(self, c, key):
        return self.bench.approval_record(c, key)

    def _delivered(self, c, key, receipt):
        if receipt.get("id") != key or receipt.get("payload_hash") != key:
            raise DeliveryError("receipt_content_conflict")
        result = self._mark(key, "delivered", "exact_receipt_reconciled", receipt=receipt)
        c.execute("UPDATE seller_actions SET state='delivered',receipt=?,detail='' WHERE id=?",
                  (canonical(receipt), key))
        self.bench.audit(c, "salesforce_receipt_reconciled", key, "salesforce-operator",
                         {"payload_hash": key, "destination_pin": self.inbox.destination_pin})
        return result

    def _pin(self, key):
        row = self.status(key)
        expected = digest({"destination": self.inbox.destination_pin,
                           "max_attempts": self.max_attempts, "ttl": self.ttl})
        if row and row["pin"] != expected:
            raise Refused("journal_destination_changed")
        return row

    def step(self, key):
        # Store BEGIN IMMEDIATE serializes dispatch and local source changes.
        # The separate journal commits intent before remote IO, surviving local rollback/death.
        with self.bench.store.tx() as c:
            action, payload = self._approved(c, key)
            row = self._pin(key)
            now = self.clock()
            if row and row["state"] in TERMINAL:
                # Restore a local acknowledgement after a crash between the two DB commits.
                if row["state"] == "delivered":
                    return self._delivered(c, key, json.loads(row["receipt"]))
                return row
            if not row:
                with self.journal() as j:
                    j.execute("INSERT INTO deliveries VALUES(?,?,'ready',0,?,0,'',NULL)",
                              (key, self.journal_pin, now))
                row = self.status(key)
            if row["attempts"] >= self.max_attempts or now - row["first_at"] >= self.ttl:
                return self._mark(key, "exhausted", "operator_reconciliation_required")
            if now < row["next_at"]:
                return row
            attempt = row["attempts"] + 1
            with self.journal() as j:
                j.execute("UPDATE deliveries SET attempts=?,state='inflight',next_at=? WHERE key=?",
                          (attempt, now + 10, key))
                j.execute("INSERT INTO events(key,at,state,detail) VALUES(?,?,'inflight','intent_committed')",
                          (key, now))
            c.execute("UPDATE seller_actions SET attempts=attempts+1 WHERE id=?", (key,))
            try:
                # Historical reconciliation precedes current consent/evidence validation.
                receipt = self.inbox.receipt(key)
                if receipt:
                    return self._delivered(c, key, receipt)
                if action["state"] not in ("approved", "retry"):
                    raise Refused("action_no_longer_authorized")
                if c.execute("SELECT 1 FROM seller_audit WHERE action='proposal_rejected' AND subject=?",
                             (action["run_id"],)).fetchone():
                    raise Refused("proposal_rejected")
                self.bench.authorize_new_effect(c, key)
                receipt = self.inbox.create(key, payload)
                return self._delivered(c, key, receipt)
            except Refused as exc:
                self.bench.audit(c, "salesforce_dispatch_blocked", key, "salesforce-operator", {"reason": str(exc)})
                return self._mark(key, "blocked", str(exc))
            except DeliveryError as exc:
                if not exc.retryable:
                    return self._mark(key, "blocked", str(exc))
                if attempt >= self.max_attempts:
                    return self._mark(key, "exhausted", "operator_reconciliation_required:" + str(exc))
                # Deterministic bounded jitter makes local fault replay reproducible.
                delay = max(min(2 ** attempt + int(key[:2], 16) % 3, 60), exc.retry_after or 0)
                if now + delay >= row["first_at"] + self.ttl:
                    return self._mark(key, "exhausted", "retry_after_exceeds_deadline")
                c.execute("UPDATE seller_actions SET state='retry',detail=? WHERE id=?", (str(exc), key))
                return self._mark(key, "retry", str(exc), next_at=now + delay)

    def reconcile_once(self, key):
        """Explicit operator read, including exhausted/rejected actions. Never POSTs or resets a budget."""
        with self.bench.store.tx() as c:
            self._approved(c, key)
            if not self._pin(key):
                with self.journal() as j:
                    j.execute("INSERT INTO deliveries VALUES(?,?,'blocked',0,?,0,'read_only',NULL)",
                              (key, self.journal_pin, self.clock()))
            receipt = self.inbox.receipt(key)
            self.bench.audit(c, "salesforce_operator_read", key, "salesforce-operator", {"found": bool(receipt)})
            if receipt:
                return self._delivered(c, key, receipt)
            return {"key": key, "state": "not_found_or_not_visible", "writes_permitted": False}
