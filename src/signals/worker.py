import json

import httpx

from .contracts import digest
from .decision import decide
from .finance import allocations, conversion_payload
from .store import Refused


def deliver_one(store, remote, clock, timeout=1, crash=None):
    # Deliberate single local execution lane. Holding this transaction serializes
    # consent admission with dispatch; the real remote boundary remains non-atomic.
    with store.tx() as c, httpx.Client(base_url=remote, timeout=timeout, trust_env=False) as client:
        row = c.execute(
            "SELECT * FROM outbox WHERE state IN ('pending','retry','uncertain') "
            "AND next_at<=? ORDER BY rowid LIMIT 1",
            (clock,),
        ).fetchone()
        if not row:
            return False
        key, payload = row["id"], json.loads(row["payload"])
        attempts = row["attempts"] + 1
        c.execute("UPDATE outbox SET attempts=? WHERE id=?", (attempts, key))

        def mark(state, detail):
            c.execute(
                "UPDATE outbox SET state=?,detail=?,next_at=? WHERE id=?",
                (state, detail, clock + min(2**attempts, 60), key),
            )

        try:
            receipt = client.get("/receipts/" + key)
            if receipt.status_code == 200:
                if receipt.json().get("payload_hash") != digest(payload):
                    mark("conflict", "receipt_payload_mismatch")
                else:
                    mark("applied", "reconciled_remote_commit")
                return True
            if receipt.status_code != 404:
                receipt.raise_for_status()
            saved = json.loads(
                c.execute("SELECT body FROM decisions WHERE id=?", (row["decision"],)).fetchone()[0]
            )
            current = decide(store.events(c, clock), row["brand"], row["account"], clock)
            saved.pop("input_seq", None)
            # Recalculate at delivery time; a harmless later clock is not itself a stale-input change.
            saved["as_of"] = clock
            if saved != current:
                mark("blocked", "decision_changed_replan_required")
                return True
            if current["blocked"] and current["blocked"] != ["suppressed_or_unknown_consent"]:
                mark("blocked", "business_policy_hold")
                return True
            if row["destination"] == "conversion" and not current["consent"]:
                mark("blocked", "conversion_suppressed")
                return True
            if row["destination"] == "conversion":
                try:
                    eligible = [
                        conversion_payload(r)
                        for r in allocations(store.events(c, clock))
                        if not r["ineligible_reason"]
                    ]
                    if payload not in eligible:
                        mark("blocked", "conversion_lineage_changed")
                        return True
                except Refused:
                    mark("blocked", "invalid_commercial_lineage")
                    return True
            revision = 0
            if row["destination"] == "crm":
                remote_state = client.get("/contacts/" + payload["external_id"])
                remote_state.raise_for_status()
                revision = remote_state.json()["revision"]
            response = client.post(
                f"/apply/{row['destination']}/{key}", json={"payload": payload, "expected_revision": revision}
            )
            if response.status_code in (409, 422):
                mark("conflict", response.text[:300])
                return True
            response.raise_for_status()
            if crash:
                crash()  # Tests kill an actual process here after the remote commit.
            if response.json().get("payload_hash") != digest(payload):
                mark("conflict", "response_payload_mismatch")
            else:
                mark("applied", "remote_receipt_verified")
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if attempts >= 4:
                mark("dead", "retry_budget_exhausted:" + type(exc).__name__)
            else:
                mark("uncertain", "reconcile_before_retry:" + type(exc).__name__)
        return True
