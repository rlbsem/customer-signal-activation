import json

import httpx
import pytest
from pydantic import ValidationError

from signals.analytics import build
from signals.contracts import AUTHORITIES
from signals.decision import decide, plan
from signals.finance import plan_conversions
from signals.fixtures import AS_OF, event, sources
from signals.reconcile import reconcile
from signals.remote import connect
from signals.store import Refused, Store
from signals.worker import deliver_one


def test_identity_reassignment_refused_even_with_new_transport_id(store):
    e = event(
        "link",
        {"session": "session-0000", "account": "account-0002", "evidence": "New asserted association"},
        "false-merge",
    )
    with pytest.raises(Refused, match="entity_revision"):
        store.ingest(e, "crm", AS_OF)


def test_opportunity_cannot_move_accounts_in_higher_revision(store):
    e = event(
        "opportunity",
        {"account": "account-0002", "opportunity": "opp-0", "stage": "won", "revision": 2},
        "reparent",
    )
    with pytest.raises(Refused, match="reparenting"):
        store.ingest(e, "crm", AS_OF)


def test_schema_boolean_and_future_timestamp_rejected(store):
    e = next(sources(1))
    e["schema_version"] = True
    with pytest.raises(ValidationError):
        store.ingest(e, "crm", AS_OF)
    e["schema_version"] = 2
    e["occurred_at"] = "2027-01-01T00:00:00Z"
    with pytest.raises(Refused, match="future_event"):
        store.ingest(e, "crm", AS_OF)


def test_fallback_provider_fills_missing_fresh_fit(tmp_path):
    s = Store(tmp_path / "fallback.sqlite")
    for e in sources(1):
        if e["kind"] == "enrichment":
            e["data"]["provider"] = "fallback"
        s.ingest(e, AUTHORITIES[e["kind"]], AS_OF)
    with s.tx() as c:
        d = decide(s.events(c, AS_OF), "cedar", "account-0000", AS_OF)
    assert d["fit"] == 30 and "account-0000-enrich" in d["input_events"]


def test_open_opportunity_can_be_qualified_without_manufactured_cash(tmp_path):
    s = Store(tmp_path / "open.sqlite")
    for e in sources(14):
        s.ingest(e, AUTHORITIES[e["kind"]], AS_OF)
    with s.tx() as c:
        d = decide(s.events(c, AS_OF), "cedar", "account-0012", AS_OF)
    assert d["stage"] == "qualified" and d["score"] == 80
    from signals.finance import allocations

    with s.tx() as c:
        assert not any(r["account"] == "account-0012" for r in allocations(s.events(c, AS_OF)))


def test_unknown_mapping_remains_unattributed(tmp_path):
    s = Store(tmp_path / "unlinked.sqlite")
    for e in sources(1):
        if e["kind"] != "link":
            s.ingest(e, AUTHORITIES[e["kind"]], AS_OF)
    with s.tx() as c:
        d = decide(s.events(c, AS_OF), "cedar", "account-0000", AS_OF)
    assert d["intent"] == 0 and d["campaign"] == "unattributed"


def test_remote_state_drift_is_observable(store, remote):
    plan(store, AS_OF)
    while deliver_one(store, remote[1], AS_OF):
        pass
    assert reconcile(store, remote[1])["matched"]
    with connect(remote[0]) as c:
        c.execute("UPDATE contacts SET body='{}' WHERE id='cedar:account-0000'")
    result = reconcile(store, remote[1])
    assert not result["matched"] and result["differences"] == ["cedar:account-0000"]


def test_exhausted_retry_is_unresolved_not_success(store, remote):
    plan(store, AS_OF)
    with store.tx() as c:
        key = c.execute("SELECT id FROM outbox ORDER BY rowid LIMIT 1").fetchone()[0]
    for clock in (AS_OF, AS_OF + 2, AS_OF + 6, AS_OF + 14):
        with connect(remote[0]) as c:
            c.execute("INSERT INTO faults VALUES(?,'unavailable')", (key,))
        deliver_one(store, remote[1], clock)
    with store.tx() as c:
        assert c.execute("SELECT state FROM outbox WHERE id=?", (key,)).fetchone()[0] == "dead"
    assert not reconcile(store, remote[1])["matched"]


def test_financial_change_after_plan_blocks_conversion(store, remote):
    plan_conversions(store, AS_OF)
    with store.tx() as c:
        c.execute("UPDATE outbox SET state='blocked' WHERE destination='crm'")
    e = event("payment", {"invoice": "invoice-0-0", "allocation": "overpay", "cents": 1}, "overpay", day=31)
    store.ingest(e, "finance", AS_OF)
    deliver_one(store, remote[1], AS_OF)
    with store.tx() as c:
        assert (
            c.execute(
                "SELECT detail FROM outbox WHERE destination='conversion' ORDER BY rowid LIMIT 1"
            ).fetchone()[0]
            == "invalid_commercial_lineage"
        )
    with connect(remote[0]) as c:
        assert c.execute("SELECT count(*) FROM conversions").fetchone()[0] == 0


def test_earlier_late_touch_restates_attribution_and_matches_clean_replay(store, tmp_path):
    before = build(store, AS_OF, tmp_path / "before")
    e = event(
        "web",
        {
            "session": "session-0000",
            "action": "page_view",
            "analytics_consent": True,
            "ads_consent": False,
            "campaign": "earlier-organic",
        },
        "late-touch",
        day=1,
    )
    store.ingest(e, "browser", AS_OF)
    after = build(store, AS_OF, tmp_path / "after")
    clean = Store(tmp_path / "clean.sqlite")
    clean.ingest(e, "browser", AS_OF)
    for source in sources(12):
        clean.ingest(source, AUTHORITIES[source["kind"]], AS_OF)
    replay = build(clean, AS_OF, tmp_path / "replay")
    assert after["lineage"] == replay["lineage"] and after["campaigns"] == replay["campaigns"]
    assert after["cash_cents"] == before["cash_cents"]
    assert any(r["campaign"] == "earlier-organic" for r in after["lineage"])


def test_destination_payload_conflict_does_not_create_another_effect(remote):
    payload = {
        "external_id": "cedar:a",
        "score": 10,
        "owner": "cedar-east",
        "lifecycle": "nurture",
        "campaign": "x",
        "decision_id": "d",
    }
    with httpx.Client(base_url=remote[1], trust_env=False) as client:
        assert (
            client.post("/apply/crm/key", json={"payload": payload, "expected_revision": 0}).status_code
            == 200
        )
        payload["score"] = 50
        assert (
            client.post("/apply/crm/key", json={"payload": payload, "expected_revision": 1}).status_code
            == 409
        )
    with connect(remote[0]) as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1
        assert json.loads(c.execute("SELECT body FROM contacts").fetchone()[0])["score"] == 10
