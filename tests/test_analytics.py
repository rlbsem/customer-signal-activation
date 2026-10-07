import json

import pytest

from signals.analytics import build, published
from signals.finance import allocations, plan_conversions
from signals.fixtures import AS_OF, event
from signals.store import Refused


def test_python_oracle_exact_money_and_conversion_exclusions(store):
    with store.tx() as c:
        rows = allocations(store.events(c, AS_OF))
    # Four won fulfillments, eight invoices, sixteen half-invoice cash allocations.
    assert len(rows) == 16
    assert sum(r["cents"] for r in rows) == 500000
    assert len([r for r in rows if not r["ineligible_reason"]]) == 8
    assert {r["campaign"] for r in rows} == {"enterprise-workflows", "partner-referral"}


def test_actual_dbt_no_invoice_fanout_and_publication_survives_bad_data(store, tmp_path):
    before = build(store, AS_OF, tmp_path / "good")
    assert before["cash_cents"] == 500000
    assert sum(r["linked_invoice_cents"] for r in before["campaigns"]) == 500000
    store.ingest(
        event("payment", {"invoice": "missing", "allocation": "orphan", "cents": 10}, "orphan", day=31),
        "finance",
        AS_OF,
    )
    with pytest.raises(Refused, match="dbt_quality_gate"):
        build(store, AS_OF, tmp_path / "bad")
    assert published(store) == before


@pytest.mark.parametrize("kind", ["lost", "overpaid", "wrong-brand", "future-fulfillment"])
def test_invalid_commercial_relationship_refused(store, kind):
    if kind == "lost":
        e = event(
            "opportunity",
            {"account": "account-0000", "opportunity": "opp-0", "stage": "lost", "revision": 2},
            "lost",
            day=29,
        )
        actor = "crm"
    elif kind == "future-fulfillment":
        e = event(
            "fulfillment",
            {"opportunity": "opp-0", "fulfillment": "fulfillment-0", "completed": True, "revision": 2},
            "future-fulfillment",
            day=31,
        )
        actor = "operations"
    else:
        e = event(
            "payment",
            {"invoice": "invoice-0-0", "allocation": "extra", "cents": 1},
            "extra",
            brand="harbour" if kind == "wrong-brand" else "cedar",
            day=31,
        )
        actor = "finance"
    store.ingest(e, actor, AS_OF)
    with store.tx() as c, pytest.raises(Refused):
        allocations(store.events(c, AS_OF))


def test_conversion_replay_and_no_call_click_fabrication(store):
    plan_conversions(store, AS_OF)
    before = store.status()
    plan_conversions(store, AS_OF)
    assert store.status() == before
    with store.tx() as c:
        rows = list(c.execute("SELECT payload FROM outbox WHERE destination='conversion'"))
    assert len(rows) == 8
    assert all(json.loads(r[0])["gclid"].startswith("synthetic-click-") for r in rows)


def test_tampered_publication_refuses_reader(store):
    with store.tx() as c:
        c.execute("INSERT INTO publication VALUES(1,'{}','fake')")
    with pytest.raises(Refused, match="tampered"):
        published(store)
