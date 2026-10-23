"""Bounded lifecycle orchestration. Single SQLite writer; independent HTTP acceptance."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from .contracts import canonical, digest
from .remote import connect
from .store import Refused

DAY = 86400
JOURNEYS = {"onboarding": (20, DAY), "quiet": (30, DAY), "expansion": (10, 0)}
SCHEMA = """
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, brand TEXT, person TEXT, source TEXT,
 event_id TEXT, revision INTEGER, effective INTEGER, observed INTEGER, kind TEXT, body TEXT, hash TEXT,
 UNIQUE(brand,source,event_id,revision));
CREATE INDEX IF NOT EXISTS events_subject ON events(brand,person,observed);
CREATE TABLE IF NOT EXISTS execution_clock(id INTEGER PRIMARY KEY, value INTEGER);
INSERT OR IGNORE INTO execution_clock VALUES(1,0);
CREATE TABLE IF NOT EXISTS policy(version INTEGER PRIMARY KEY, body TEXT, hash TEXT);
CREATE TRIGGER IF NOT EXISTS policy_immutable BEFORE UPDATE ON policy BEGIN SELECT RAISE(ABORT,'immutable policy'); END;
CREATE TRIGGER IF NOT EXISTS policy_no_delete BEFORE DELETE ON policy BEGIN SELECT RAISE(ABORT,'immutable policy'); END;
CREATE TABLE IF NOT EXISTS enrollment(id TEXT PRIMARY KEY,brand TEXT,person TEXT,journey TEXT,
 version INTEGER,epoch INTEGER,due INTEGER,state TEXT,entry TEXT,UNIQUE(brand,person,journey,entry));
CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY,enrollment TEXT,epoch INTEGER,payload TEXT,
 evidence TEXT,state TEXT,approved TEXT,reserved INTEGER,attempts INTEGER DEFAULT 0,next_at INTEGER DEFAULT 0,
 detail TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS actions_enrollment ON actions(enrollment);
CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY,action TEXT,at INTEGER,event TEXT,body TEXT);
CREATE TRIGGER IF NOT EXISTS events_immutable BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS history_immutable BEFORE UPDATE ON history BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history BEGIN SELECT RAISE(ABORT,'immutable'); END;
"""
SOURCES = {
    "identity": "crm",
    "commercial": "crm",
    "preference": "preferences",
    "trial": "product",
    "activity": "product",
    "coverage": "product",
    "conversion": "crm",
}
FIELDS = {
    "identity": {"account", "owner", "zone"},
    "commercial": {"state", "opportunity", "owner"},
    "preference": {"channel", "purpose", "allowed"},
    "trial": {"started"},
    "activity": {"active"},
    "coverage": {"after", "through"},
    "conversion": {"converted"},
}


def quiet(now, zone):
    """UTC clock mapped into real IANA local time; no invented ambiguous local timestamp."""
    hour = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo(zone)).hour
    return hour < 9 or hour >= 20


class Lifecycle:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as database:
            database.execute("PRAGMA journal_mode=WAL")
        with connect(self.path) as c:
            c.executescript(SCHEMA)
            from .lifecycle_experiment import initialize

            initialize(c)
            body = canonical({"journeys": JOURNEYS, "daily": 1, "weekly": 2, "quiet": [20, 9]})
            c.execute("INSERT OR IGNORE INTO policy VALUES(1,?,?)", (body, digest(json.loads(body))))

    def log(self, c, key, now, event, body):
        c.execute(
            "INSERT INTO history(action,at,event,body) VALUES(?,?,?,?)", (key, now, event, canonical(body))
        )

    def ingest(self, brand, person, source, event_id, revision, effective, observed, kind, body):
        if (
            brand not in {"cedar", "atlas"}
            or not person.startswith("synthetic-")
            or not event_id
            or kind not in SOURCES
            or source != SOURCES[kind]
            or set(body) != FIELDS[kind]
            or type(revision) is not int
            or revision < 1
            or type(effective) is not int
            or type(observed) is not int
            or effective > observed
        ):
            raise Refused("source_contract")
        if kind == "identity":
            if not body["account"].startswith("synthetic-") or not body["owner"]:
                raise Refused("identity_contract")
            ZoneInfo(body["zone"])
        if kind == "preference" and (
            body["channel"] != "email" or body["purpose"] != "marketing" or type(body["allowed"]) is not bool
        ):
            raise Refused("preference_contract")
        if kind == "commercial" and (
            body["state"] not in {"trial", "customer"}
            or type(body["opportunity"]) is not bool
            or not body["owner"]
        ):
            raise Refused("commercial_contract")
        if kind == "coverage" and (
            type(body["after"]) is not int
            or type(body["through"]) is not int
            or body["after"] > body["through"]
            or body["through"] > observed
        ):
            raise Refused("coverage_contract")
        if kind in {"trial", "activity", "conversion"} and type(next(iter(body.values()))) is not bool:
            raise Refused("boolean_contract")
        if kind == "activity" and body["active"] is not True:
            raise Refused("positive_activity_only")
        value = digest(
            {
                "brand": brand,
                "person": person,
                "source": source,
                "effective": effective,
                "kind": kind,
                "body": body,
            }
        )
        with connect(self.path) as c:
            old = c.execute(
                "SELECT hash FROM events WHERE brand=? AND source=? AND event_id=? AND revision=?",
                (brand, source, event_id, revision),
            ).fetchone()
            if old:
                if old[0] != value:
                    raise Refused("event_collision")
                return "duplicate"
            previous = c.execute(
                "SELECT person,kind FROM events WHERE brand=? AND source=? AND event_id=? LIMIT 1",
                (brand, source, event_id),
            ).fetchone()
            if previous and tuple(previous) != (person, kind):
                raise Refused("revision_identity_changed")
            c.execute(
                "INSERT INTO events VALUES(NULL,?,?,?,?,?,?,?,?,?,?)",
                (
                    brand,
                    person,
                    source,
                    event_id,
                    revision,
                    effective,
                    observed,
                    kind,
                    canonical(body),
                    value,
                ),
            )
        return "accepted"

    def facts(self, c, brand, person, now):
        rows = c.execute(
            """WITH ranked AS (SELECT *,row_number() OVER(
          PARTITION BY source,event_id ORDER BY revision DESC) r FROM events
          WHERE brand=? AND person=? AND observed<=?) SELECT * FROM ranked WHERE r=1 AND effective<=?
          ORDER BY effective,seq""",
            (brand, person, now, now),
        ).fetchall()
        result = {}
        for row in rows:
            result[row["kind"]] = json.loads(row["body"]) | {
                "_hash": row["hash"],
                "_at": row["effective"],
                "_id": row["event_id"],
            }
        return result

    def eligibility(self, f, journey, now):
        if not all(k in f for k in ("identity", "commercial", "preference")):
            return "missing_authority"
        if f["identity"]["owner"] != f["commercial"]["owner"]:
            return "owner_changed"
        if not f["preference"]["allowed"]:
            return "permission_denied"
        if journey in {"onboarding", "quiet"}:
            if f["commercial"]["state"] != "trial" or f.get("conversion", {}).get("converted"):
                return "converted_or_not_trial"
            if not f.get("trial", {}).get("started"):
                return "missing_trial"
        elif f["commercial"]["state"] != "customer":
            return "not_customer"
        if journey == "quiet":
            coverage = f.get("coverage", {})
            if coverage.get("after", now) > now - DAY or coverage.get("through", 0) < now:
                return "coverage_missing_or_expired"
            if f.get("activity", {}).get("active") and f["activity"]["_at"] > now - DAY:
                return "recent_activity"
        if journey == "expansion" and f["commercial"]["opportunity"]:
            return "owner_review"
        if quiet(now, f["identity"]["zone"]):
            return "quiet_hours"
        return "eligible"

    def tick(self, now):
        if type(now) is not int:
            raise Refused("integer_clock_required")
        with connect(self.path) as c:
            if now < c.execute("SELECT value FROM execution_clock WHERE id=1").fetchone()[0]:
                raise Refused("execution_clock_regression")
            c.execute("UPDATE execution_clock SET value=? WHERE id=1", (now,))
            people = c.execute("SELECT DISTINCT brand,person FROM events").fetchall()
            for brand, person in people:
                f = self.facts(c, brand, person, now)
                for journey, (_, delay) in JOURNEYS.items():
                    entry = f.get("trial" if journey != "expansion" else "commercial")
                    if not entry or (journey == "expansion" and entry["state"] != "customer"):
                        continue
                    key = digest([brand, person, journey, entry["_id"]])
                    c.execute(
                        "INSERT OR IGNORE INTO enrollment VALUES(?,?,?,?,1,1,?,?,?)",
                        (key, brand, person, journey, entry["_at"] + delay, "active", entry["_id"]),
                    )
            for e in c.execute("SELECT * FROM enrollment WHERE state='active' AND due<=?", (now,)).fetchall():
                f = self.facts(c, e["brand"], e["person"], now)
                reason = self.eligibility(f, e["journey"], now)
                key = digest([e["id"], e["epoch"]])
                payload = {
                    "brand": e["brand"],
                    "person": e["person"],
                    "journey": e["journey"],
                    "version": e["version"],
                    "channel": "email",
                    "purpose": "marketing",
                    "text": {
                        "onboarding": "Explore your trial setup.",
                        "quiet": "Would trial assistance help?",
                        "expansion": "Explore additional product education.",
                    }[e["journey"]],
                }
                evidence = digest(f)
                old = c.execute("SELECT * FROM actions WHERE id=?", (key,)).fetchone()
                if not old:
                    c.execute(
                        "INSERT INTO actions(id,enrollment,epoch,payload,evidence,state) VALUES(?,?,?,?,?,?)",
                        (key, e["id"], e["epoch"], canonical(payload), evidence, "candidate"),
                    )
                    self.log(c, key, now, "candidate", {"reason": reason})
                elif old["state"] in {"candidate", "approved", "blocked"} and old["evidence"] != evidence:
                    c.execute(
                        "UPDATE actions SET evidence=?,approved=NULL,state='candidate' WHERE id=?",
                        (evidence, key),
                    )
                    self.log(c, key, now, "context_changed", {"reason": reason})
                if reason == "converted_or_not_trial":
                    c.execute("UPDATE enrollment SET state='exited',epoch=epoch+1 WHERE id=?", (e["id"],))
                    c.execute("UPDATE actions SET state='cancelled' WHERE id=? AND reserved IS NULL", (key,))
                    self.log(c, key, now, "conversion_exit", {})
        return self.view(now)

    def view(self, now):
        with connect(self.path) as c:
            result = []
            for e in c.execute("SELECT * FROM enrollment ORDER BY brand,person,journey"):
                f = self.facts(c, e["brand"], e["person"], now)
                for a in c.execute("SELECT * FROM actions WHERE enrollment=? ORDER BY rowid", (e["id"],)):
                    result.append(
                        dict(a)
                        | {
                            "brand": e["brand"],
                            "person": e["person"],
                            "journey": e["journey"],
                            "version": e["version"],
                            "due": e["due"],
                            "reason": self.eligibility(f, e["journey"], now),
                            "priority": JOURNEYS[e["journey"]][0],
                            "approval_hash": digest([json.loads(a["payload"]), a["evidence"], a["epoch"]]),
                            "sources": f,
                        }
                    )
            for row in result:
                policy = json.loads(
                    c.execute("SELECT body FROM policy WHERE version=?", (row["version"],)).fetchone()[0]
                )
                if row["journey"] in policy.get("paused", []):
                    row["reason"] = "journey_paused"
                if row["reason"] == "eligible" and row["state"] not in {
                    "accepted",
                    "cancelled",
                    "uncertain",
                    "exhausted",
                }:
                    peers = [
                        r
                        for r in result
                        if r["brand"] == row["brand"]
                        and r["person"] == row["person"]
                        and r["reason"] == "eligible"
                        and r["state"] not in {"accepted", "cancelled", "uncertain", "exhausted"}
                    ]
                    if peers and sorted(peers, key=lambda r: (-r["priority"], r["id"]))[0]["id"] != row["id"]:
                        row["reason"] = "higher_priority_journey"
            return {
                "now": now,
                "actions": result,
                "timers": [dict(r) for r in c.execute("SELECT * FROM enrollment")],
                "timeline": [dict(r) for r in c.execute("SELECT * FROM history ORDER BY seq")],
                "scope": "Local synthetic lifecycle; no vendor messages or native marketing execution",
            }

    def approve(self, key, expected, now):
        self.tick(now)
        with connect(self.path) as c:
            a = c.execute("SELECT * FROM actions WHERE id=?", (key,)).fetchone()
            if not a or a["state"] not in {"candidate", "blocked", "held"}:
                raise Refused("not_reviewable")
            actual = digest([json.loads(a["payload"]), a["evidence"], a["epoch"]])
            if expected != actual:
                raise Refused("approval_changed")
            c.execute("UPDATE actions SET approved=?,state='approved' WHERE id=?", (actual, key))
            self.log(c, key, now, "approved", {"hash": actual})

    def register_policy(self, version, paused=()):
        if type(version) is not int or version < 2 or not set(paused) <= set(JOURNEYS):
            raise Refused("invalid_policy")
        body = canonical(
            {"journeys": JOURNEYS, "daily": 1, "weekly": 2, "quiet": [20, 9], "paused": sorted(paused)}
        )
        with connect(self.path) as c:
            old = c.execute("SELECT body FROM policy WHERE version=?", (version,)).fetchone()
            if old and old[0] != body:
                raise Refused("policy_collision")
            c.execute("INSERT OR IGNORE INTO policy VALUES(?,?,?)", (version, body, digest(json.loads(body))))

    def migrate(self, enrollment, version, now):
        with connect(self.path) as c:
            e = c.execute("SELECT * FROM enrollment WHERE id=?", (enrollment,)).fetchone()
            if not e or e["state"] != "active":
                raise Refused("migration_precondition")
            if c.execute(
                "SELECT 1 FROM actions WHERE enrollment=? AND reserved IS NOT NULL AND state!=?",
                (enrollment, "accepted"),
            ).fetchone():
                raise Refused("unresolved_reservation")
            if not c.execute("SELECT 1 FROM policy WHERE version=?", (version,)).fetchone():
                raise Refused("unknown_policy")
            c.execute(
                "UPDATE actions SET state='cancelled' WHERE enrollment=? AND reserved IS NULL", (enrollment,)
            )
            c.execute("UPDATE enrollment SET version=?,epoch=epoch+1 WHERE id=?", (version, enrollment))
            self.log(c, enrollment, now, "migration", {"version": version})

    def dispatch(self, key, now, url, *, lose_ack=False, kill=False):
        from urllib.parse import urlsplit

        p = urlsplit(url)
        if (
            p.scheme != "http"
            or p.hostname != "127.0.0.1"
            or p.path not in {"", "/"}
            or p.username
            or p.query
            or p.fragment
        ):
            raise Refused("loopback_destination_required")
        self.tick(now)
        peers = self.view(now)["actions"]
        with connect(self.path) as c, httpx.Client(base_url=url, trust_env=False, timeout=2) as client:
            a = c.execute("SELECT * FROM actions WHERE id=?", (key,)).fetchone()
            if not a:
                raise Refused("unknown_action")
            payload = json.loads(a["payload"])
            # Historical reconciliation precedes current authorization, even after conversion/revocation.
            try:
                receipt = client.get("/receipts/" + key)
                if receipt.status_code == 200:
                    if (
                        receipt.json().get("payload_hash") != digest(payload)
                        or receipt.json().get("id") != key
                        or receipt.json().get("accepted") is not True
                    ):
                        raise Refused("receipt_conflict")
                    if a["reserved"] is None:
                        raise Refused("unreserved_remote_effect")
                    c.execute(
                        "UPDATE actions SET reserved=CASE WHEN state='accepted' THEN reserved ELSE ? END, state='accepted',detail='independent_receipt' WHERE id=?",
                        (now, key),
                    )
                    self.log(c, key, now, "accepted", receipt.json())
                    return "accepted"
                if receipt.status_code != 404:
                    raise Refused("receipt_unavailable")
            except httpx.TransportError:
                raise Refused("receipt_unavailable")
            if a["state"] in {"accepted", "cancelled", "exhausted", "held"}:
                return a["state"]
            if a["attempts"] >= 3:
                c.execute("UPDATE actions SET state='exhausted',detail='attempt_limit' WHERE id=?", (key,))
                return "exhausted"
            if a["next_at"] > now:
                return "backoff"
            e = c.execute("SELECT * FROM enrollment WHERE id=?", (a["enrollment"],)).fetchone()
            f = self.facts(c, e["brand"], e["person"], now)
            reason = self.eligibility(f, e["journey"], now)
            from .lifecycle_experiment import guard

            experiment_reason = guard(c, e, now)
            if experiment_reason:
                self.log(c, key, now, "experiment_suppressed", {"reason": experiment_reason})
                return experiment_reason
            policy = json.loads(
                c.execute("SELECT body FROM policy WHERE version=?", (e["version"],)).fetchone()[0]
            )
            if e["journey"] in policy.get("paused", []):
                reason = "journey_paused"
            if a["epoch"] != e["epoch"] or e["state"] != "active":
                reason = "stale_epoch"
            if a["evidence"] != digest(f):
                reason = "context_changed"
            if a["approved"] != digest([payload, a["evidence"], a["epoch"]]):
                reason = "approval_required"
            if reason == "eligible":
                reason = next(r["reason"] for r in peers if r["id"] == key)
            if reason != "eligible":
                c.execute("UPDATE actions SET detail=? WHERE id=?", (reason, key))
                self.log(c, key, now, "held", {"reason": reason})
                return reason
            used = c.execute(
                """SELECT a.* FROM actions a JOIN enrollment e ON e.id=a.enrollment
                WHERE e.brand=? AND e.person=? AND a.reserved IS NOT NULL AND a.id!=?""",
                (e["brand"], e["person"], key),
            ).fetchall()
            if (
                any(r["state"] != "accepted" or r["reserved"] > now - DAY for r in used)
                or sum(r["reserved"] > now - 7 * DAY for r in used) >= 2
            ):
                self.log(c, key, now, "held", {"reason": "contact_limit"})
                return "contact_limit"
            c.execute(
                "UPDATE actions SET state='uncertain',reserved=coalesce(reserved,?),attempts=attempts+1 WHERE id=?",
                (now, key),
            )
            self.log(c, key, now, "attempt", {})
        # Durable reservation commits before remote I/O. Re-entry is serialized at reservation above;
        # the independent destination enforces the same action key on concurrent retries.
        try:
            response = httpx.post(url + "/accept/" + key, json=payload, trust_env=False, timeout=2)
            if response.status_code == 200 and kill:
                os._exit(86)
            if response.status_code == 200 and lose_ack:
                return "uncertain"
            if response.status_code == 200:
                return self.dispatch(key, now, url)
            if response.status_code == 429:
                with connect(self.path) as c:
                    attempts = c.execute("SELECT attempts FROM actions WHERE id=?", (key,)).fetchone()[0]
                    c.execute(
                        "UPDATE actions SET state=?,next_at=?,detail=? WHERE id=?",
                        ("exhausted" if attempts >= 3 else "approved", now + 2**attempts, "rate_limit", key),
                    )
                return "rate_limit"
            return "uncertain"
        except httpx.TransportError:
            return "uncertain"
