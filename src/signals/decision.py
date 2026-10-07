"""Explicit business policy; no learned propensity or causal attribution claim."""

from .contracts import canonical, digest
from .store import Refused

POLICY = "fit-intent-route/v2"
DAY = 86400
OWNERS = {
    "cedar": {"ON": "cedar-east", "BC": "cedar-west"},
    "harbour": {"ON": "harbour-east", "BC": "harbour-west"},
}


def latest(events, kind, **criteria):
    rows = [
        e for e in events if e["kind"] == kind and all(e["data"].get(k) == v for k, v in criteria.items())
    ]
    return max(rows, key=lambda e: e["data"].get("revision", 0), default=None)


def accounts(events):
    return sorted({(e["brand"], e["data"]["account"]) for e in events if e["kind"] == "profile"})


def decide(events, brand, account, as_of):
    rows = [e for e in events if e["brand"] == brand]
    profile = latest(rows, "profile", account=account)
    if not profile:
        raise Refused("unknown_account")
    consent = latest(rows, "consent", account=account)
    links = [e for e in rows if e["kind"] == "link" and e["data"]["account"] == account]
    sessions = {e["data"]["session"] for e in links}
    signals = [
        e
        for e in rows
        if (e["kind"] == "web" and e["data"]["session"] in sessions)
        or (e["kind"] == "call" and e["data"]["account"] == account)
    ]
    recent = [e for e in signals if as_of - 7 * DAY <= e["occurred"] <= as_of]
    actions = {e["data"]["action"] for e in recent if e["kind"] == "web"}
    intent = (30 if "contact_sales" in actions else 0) + (20 if "pricing_view" in actions else 0)
    intent += 20 if any(e["kind"] == "call" and e["data"]["qualified"] for e in recent) else 0
    facts, notes = [profile["event_id"]], []
    employees = profile["data"]["employees"]
    # Waterfall providers cannot overwrite a present CRM fact.
    enrichment = [latest(rows, "enrichment", account=account, provider=p) for p in ("primary", "fallback")]
    fresh = [e for e in enrichment if e and as_of - 30 * DAY <= e["occurred"] <= as_of]
    facts.extend(e["event_id"] for e in fresh)
    if employees is None and fresh:
        if len({e["data"]["employees"] >= 20 for e in fresh}) > 1:
            notes.append("enrichment_fit_conflict")
        else:
            employees = fresh[0]["data"]["employees"]
            facts.append(fresh[0]["event_id"])
    elif employees is not None and any(e["data"]["employees"] != employees for e in fresh):
        notes.append("crm_fit_authority_preserved")
    fit = 30 if employees is not None and employees >= 20 else 0
    expected_owner = OWNERS[brand].get(profile["data"]["region"])
    owner = profile["data"]["owner"] or expected_owner
    blocked = []
    if not expected_owner or owner != expected_owner:
        blocked.append("territory_or_owner_conflict")
    if "enrichment_fit_conflict" in notes:
        blocked.append("enrichment_fit_conflict")
    permission = bool(consent and consent["data"]["allowed"])
    if not permission:
        blocked.append("suppressed_or_unknown_consent")
    stage = "qualified" if fit + intent >= 60 else "nurture"
    if blocked:
        stage = "hold"
    won = any(
        e["kind"] == "opportunity" and e["data"]["stage"] == "won"
        for e in [
            latest(rows, "opportunity", opportunity=x)
            for x in {
                e["data"]["opportunity"]
                for e in rows
                if e["kind"] == "opportunity" and e["data"]["account"] == account
            }
        ]
    )
    facts.extend(
        e["event_id"] for e in rows if e["kind"] == "opportunity" and e["data"]["account"] == account
    )
    if won and not blocked:
        stage = "customer"  # Stops prospect nurture; does not reset the sales-owned opportunity.
    touches = sorted(
        [e for e in signals if e["data"].get("campaign")], key=lambda e: (e["occurred"], e["event_id"])
    )
    source = touches[0] if touches else None
    return {
        "brand": brand,
        "account": account,
        "as_of": as_of,
        "policy": POLICY,
        "fit": fit,
        "intent": intent,
        "score": fit + intent,
        "owner": owner,
        "stage": stage,
        "consent": permission,
        "blocked": blocked,
        "notes": notes,
        "campaign": source["data"]["campaign"] if source else "unattributed",
        "touch_id": source["event_id"] if source else None,
        "input_events": sorted(
            set(facts + [e["event_id"] for e in recent + links] + ([consent["event_id"]] if consent else []))
        ),
    }


def plan(store, as_of):
    with store.tx() as c:
        events = store.events(c, as_of)
        watermark = c.execute("SELECT coalesce(max(seq),0) FROM events").fetchone()[0]
        results = []
        for brand, account in accounts(events):
            d = decide(events, brand, account, as_of)
            d["input_seq"] = watermark
            key = digest(d)
            c.execute(
                "INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?,?)",
                (key, brand, account, as_of, watermark, canonical(d)),
            )
            payload = {
                "external_id": f"{brand}:{account}",
                "score": d["score"],
                "owner": d["owner"],
                "lifecycle": d["stage"],
                "campaign": d["campaign"],
                "decision_id": key,
            }
            c.execute(
                "INSERT OR IGNORE INTO outbox(id,decision,destination,brand,account,payload) VALUES(?,?,?,?,?,?)",
                ("crm:" + key, key, "crm", brand, account, canonical(payload)),
            )
            results.append(dict(d, id=key))
        return results
