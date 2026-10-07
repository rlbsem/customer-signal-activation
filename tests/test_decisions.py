import pytest

from signals.decision import DAY, decide, plan
from signals.fixtures import AS_OF, event


def decision(store, account="account-0000", brand="cedar", clock=AS_OF):
    with store.tx() as c:
        return decide(store.events(c, clock), brand, account, clock)


@pytest.mark.parametrize(
    "account,stage,score",
    [
        ("account-0000", "customer", 80),
        ("account-0002", "nurture", 50),
        ("account-0004", "hold", 80),
        ("account-0006", "hold", 80),
        ("account-0008", "hold", 50),
        ("account-0010", "customer", 50),
    ],
)
def test_business_segments_have_explained_different_decisions(store, account, stage, score):
    d = decision(store, account)
    assert (d["stage"], d["score"]) == (stage, score)
    assert d["fit"] + d["intent"] == d["score"]


def test_repeated_page_signals_do_not_inflate_score(store):
    before = decision(store)
    for i in range(20):
        store.ingest(
            event(
                "web",
                {
                    "session": "session-0000",
                    "action": "pricing_view",
                    "analytics_consent": True,
                    "ads_consent": False,
                },
                f"repeat-{i}",
            ),
            "browser",
            AS_OF,
        )
    assert decision(store)["score"] == before["score"]


def test_freshness_expires_without_new_events(store):
    d = decision(store, clock=AS_OF + 31 * DAY)
    assert d["score"] == 0


def test_crm_fit_and_sales_owner_cannot_be_overwritten(store):
    store.ingest(
        event(
            "profile",
            {
                "account": "account-0000",
                "region": "ON",
                "employees": 5,
                "owner": "sales-specialist",
                "revision": 2,
            },
            "crm-change",
        ),
        "crm",
        AS_OF,
    )
    d = decision(store)
    assert d["fit"] == 0 and "crm_fit_authority_preserved" in d["notes"]
    assert d["blocked"] == ["territory_or_owner_conflict"]


def test_stale_revision_does_not_regress_consent(store):
    store.ingest(
        event("consent", {"account": "account-0000", "allowed": False, "revision": 3}, "revoke"),
        "privacy",
        AS_OF,
    )
    store.ingest(
        event("consent", {"account": "account-0000", "allowed": True, "revision": 2}, "late-old"),
        "privacy",
        AS_OF,
    )
    assert not decision(store)["consent"]


def test_brand_scoped_session_never_cross_links(store):
    store.ingest(
        event(
            "web",
            {
                "session": "session-0000",
                "action": "contact_sales",
                "analytics_consent": True,
                "ads_consent": False,
                "campaign": "wrong-brand",
            },
            "foreign",
            "harbour",
            1,
        ),
        "browser",
        AS_OF,
    )
    assert decision(store)["campaign"] == "enterprise-workflows"


def test_plan_replay_same_decisions_and_outbox(store):
    a = plan(store, AS_OF)
    status = store.status()
    assert plan(store, AS_OF) == a and store.status() == status
