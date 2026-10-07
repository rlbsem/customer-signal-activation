"""Conservative operational lineage and conversion eligibility, independently of SQL."""

from .contracts import canonical, digest
from .decision import DAY, latest, plan
from .store import Refused


def allocations(events):
    result = []
    for brand in ("cedar", "harbour"):
        rows = [e for e in events if e["brand"] == brand]
        invoices = {e["data"]["invoice"]: e for e in rows if e["kind"] == "invoice"}
        paid = {}
        for payment in [e for e in rows if e["kind"] == "payment"]:
            p = payment["data"]
            invoice = invoices.get(p["invoice"])
            if not invoice:
                raise Refused("orphan_payment")
            inv = invoice["data"]
            fulfillment = latest(rows, "fulfillment", fulfillment=inv["fulfillment"])
            opp = (
                latest(rows, "opportunity", opportunity=fulfillment["data"]["opportunity"])
                if fulfillment
                else None
            )
            if not fulfillment or not opp or not latest(rows, "profile", account=opp["data"]["account"]):
                raise Refused("broken_commercial_lineage")
            if not fulfillment["data"]["completed"] or opp["data"]["stage"] != "won":
                raise Refused("cash_without_won_completed_fulfillment")
            if not opp["occurred"] <= fulfillment["occurred"] <= invoice["occurred"] <= payment["occurred"]:
                raise Refused("impossible_commercial_timeline")
            paid[p["invoice"]] = paid.get(p["invoice"], 0) + p["cents"]
            if paid[p["invoice"]] > inv["cents"]:
                raise Refused("overallocated_invoice")
            account = opp["data"]["account"]
            sessions = {
                e["data"]["session"] for e in rows if e["kind"] == "link" and e["data"]["account"] == account
            }
            touches = [
                e
                for e in rows
                if (
                    (e["kind"] == "web" and e["data"]["session"] in sessions)
                    or (e["kind"] == "call" and e["data"]["account"] == account)
                )
                and e["data"].get("campaign")
                and e["occurred"] <= opp["occurred"]
            ]
            touch = min(touches, key=lambda e: (e["occurred"], e["event_id"])) if touches else None
            reason = None
            if not touch or touch["kind"] != "web" or not touch["data"]["gclid"]:
                reason = "no_eligible_click_id"
            elif not 0 <= payment["occurred"] - touch["occurred"] <= 90 * DAY:
                reason = "click_outside_90_day_window"
            consent = latest(rows, "consent", account=account)
            if not consent or not consent["data"]["allowed"]:
                reason = "suppressed_or_unknown_consent"
            result.append(
                {
                    "brand": brand,
                    "account": account,
                    "allocation": p["allocation"],
                    "invoice": p["invoice"],
                    "invoice_cents": inv["cents"],
                    "fulfillment": inv["fulfillment"],
                    "opportunity": opp["data"]["opportunity"],
                    "cents": p["cents"],
                    "campaign": touch["data"]["campaign"] if touch else "unattributed",
                    "touch_id": touch["event_id"] if touch else None,
                    "gclid": touch["data"].get("gclid", "") if touch else "",
                    "conversion_time": payment["occurred_at"],
                    "ineligible_reason": reason,
                }
            )
    return sorted(result, key=lambda r: (r["brand"], r["allocation"]))


def plan_conversions(store, as_of):
    decisions = {(d["brand"], d["account"]): d for d in plan(store, as_of)}
    with store.tx() as c:
        rows = allocations(store.events(c, as_of))
        for r in rows:
            if r["ineligible_reason"]:
                continue
            d = decisions[r["brand"], r["account"]]
            payload = conversion_payload(r)
            key = "conversion:" + digest(payload)
            c.execute(
                "INSERT OR IGNORE INTO outbox(id,decision,destination,brand,account,payload) VALUES(?,?,?,?,?,?)",
                (key, d["id"], "conversion", r["brand"], r["account"], canonical(payload)),
            )
            c.execute(
                "UPDATE outbox SET decision=?,state='pending',attempts=0,next_at=0,detail='' "
                "WHERE id=? AND state='blocked'",
                (d["id"], key),
            )
        return rows


def conversion_payload(r):
    return {
        "order_id": f"{r['brand']}:{r['allocation']}",
        "gclid": r["gclid"],
        "conversion_time": r["conversion_time"],
        "value_cents": r["cents"],
        "currency": "CAD",
        "account": r["account"],
        "brand": r["brand"],
        "invoice": r["invoice"],
        "touch_id": r["touch_id"],
    }
