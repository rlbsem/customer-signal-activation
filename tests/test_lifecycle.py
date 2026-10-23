import concurrent.futures
import subprocess
import sys

import pytest
from signals.lifecycle import Lifecycle, DAY, quiet
from signals.lifecycle_fixtures import BASE, seed
from signals.lifecycle_destination import app
from signals.harness import serve
from signals.remote import connect
from signals.store import Refused


@pytest.fixture
def engine(tmp_path):
    e = Lifecycle(tmp_path / "core.sqlite")
    seed(e)
    return e


def action(e, person=0, journey="quiet", now=BASE):
    return next(
        a
        for a in e.view(now)["actions"]
        if a["person"] == f"synthetic-{person:04d}" and a["journey"] == journey
    )


def approve(e, a, now=BASE):
    e.approve(a["id"], a["approval_hash"], now)


def test_reference_priorities_and_expected(engine):
    expected = [
        "eligible",
        "permission_denied",
        "coverage_missing_or_expired",
        "owner_review",
        "eligible",
        "owner_changed",
        "recent_activity",
        "eligible",
        "permission_denied",
        "eligible",
        "eligible",
        "eligible",
    ]
    for i, reason in enumerate(expected):
        assert action(engine, i, "expansion" if i in {3, 4} else "quiet")["reason"] == reason
    assert action(engine, 0, "onboarding")["reason"] == "higher_priority_journey"
    seed(engine)
    assert len(engine.view(BASE)["timers"]) == 26


def test_lost_ack_revocation_and_independent_readback(engine, tmp_path):
    a = action(engine)
    approve(engine, a)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        assert engine.dispatch(a["id"], BASE, url, lose_ack=True) == "uncertain"
        engine.ingest(
            "cedar",
            "synthetic-0000",
            "preferences",
            "synthetic-0000-preference",
            2,
            BASE + 1,
            BASE + 1,
            "preference",
            {"channel": "email", "purpose": "marketing", "allowed": False},
        )
        assert engine.dispatch(a["id"], BASE + 1, url) == "accepted"
        import httpx

        assert httpx.get(url + "/receipts/" + a["id"]).json()["accepted"]
        assert engine.dispatch(action(engine, 0, "onboarding", BASE + 1)["id"], BASE + 1, url) != "accepted"
    with connect(tmp_path / "remote.sqlite") as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1


def test_preference_before_dispatch_and_collision(engine, tmp_path):
    a = action(engine)
    approve(engine, a)
    engine.ingest(
        "cedar",
        "synthetic-0000",
        "preferences",
        "synthetic-0000-preference",
        2,
        BASE + 1,
        BASE + 1,
        "preference",
        {"channel": "email", "purpose": "marketing", "allowed": False},
    )
    with serve(app(tmp_path / "remote.sqlite")) as url:
        assert engine.dispatch(a["id"], BASE + 1, url) != "accepted"
    with pytest.raises(Refused, match="collision"):
        engine.ingest(
            "cedar",
            "synthetic-0000",
            "preferences",
            "synthetic-0000-preference",
            2,
            BASE + 1,
            BASE + 1,
            "preference",
            {"channel": "email", "purpose": "marketing", "allowed": True},
        )
    engine.ingest(
        "cedar",
        "synthetic-0000",
        "preferences",
        "synthetic-0000-preference",
        1,
        BASE - DAY,
        BASE + 2,
        "preference",
        {"channel": "email", "purpose": "marketing", "allowed": True},
    )
    assert action(engine, 0, now=BASE + 2)["sources"]["preference"]["allowed"] is False


def test_real_process_death_after_acceptance(engine, tmp_path):
    a = action(engine)
    approve(engine, a)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        code = "from signals.lifecycle import Lifecycle; import sys; Lifecycle(sys.argv[1]).dispatch(sys.argv[2],int(sys.argv[3]),sys.argv[4],kill=True)"
        p = subprocess.run([sys.executable, "-c", code, engine.path, a["id"], str(BASE), url])
        assert p.returncode == 86
        restarted = Lifecycle(engine.path)
        assert action(restarted)["state"] == "uncertain"
        assert restarted.dispatch(a["id"], BASE, url) == "accepted"
    with connect(tmp_path / "remote.sqlite") as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1


def test_racing_workers(engine, tmp_path):
    a = action(engine)
    approve(engine, a)
    with serve(app(tmp_path / "remote.sqlite")) as url, concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: Lifecycle(engine.path).dispatch(a["id"], BASE, url), range(2)))
        assert results == ["accepted", "accepted"]
    with connect(tmp_path / "remote.sqlite") as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1


def test_unknown_outcome_retains_capacity(engine, tmp_path):
    a = action(engine)
    approve(engine, a)
    dest = tmp_path / "remote.sqlite"
    with serve(app(dest)) as url:
        with connect(dest) as c:
            c.execute("INSERT INTO faults VALUES(?,?)", (a["id"], "unavailable"))
        assert engine.dispatch(a["id"], BASE, url) == "uncertain"
        assert action(engine)["reserved"] == BASE
        # Even weeks later, an unresolved reservation remains occupied.
        with connect(engine.path) as c:
            rows = c.execute("SELECT reserved,state FROM actions WHERE id=?", (a["id"],)).fetchone()
            assert tuple(rows) == (BASE, "uncertain")


def test_conversion_exit_and_timer_restart(engine):
    assert Lifecycle(engine.path).view(BASE)["timers"] == engine.view(BASE)["timers"]
    engine.ingest(
        "cedar",
        "synthetic-0000",
        "crm",
        "conversion",
        1,
        BASE + 1,
        BASE + 1,
        "conversion",
        {"converted": True},
    )
    engine.tick(BASE + 1)
    assert action(engine, 0, now=BASE + 1)["state"] == "cancelled"
    assert all(
        t["state"] == "exited" for t in engine.view(BASE + 1)["timers"] if t["person"] == "synthetic-0000"
    )


def test_dst_and_quiet_hours():
    from datetime import datetime

    for stamp in [
        "2026-03-08T06:30:00+00:00",
        "2026-03-08T07:30:00+00:00",
        "2026-11-01T05:30:00+00:00",
        "2026-11-01T06:30:00+00:00",
    ]:
        assert quiet(int(datetime.fromisoformat(stamp).timestamp()), "America/Toronto")
    assert not quiet(BASE, "America/Toronto")


def test_stale_approval_and_migration(engine, tmp_path):
    a = action(engine)
    approve(engine, a)
    with connect(engine.path) as c:
        p = c.execute("SELECT body,hash FROM policy WHERE version=1").fetchone()
        c.execute("INSERT INTO policy VALUES(2,?,?)", tuple(p))
    engine.migrate(a["enrollment"], 2, BASE)
    engine.tick(BASE)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        assert engine.dispatch(a["id"], BASE, url) == "cancelled"
    assert any(r["version"] == 2 and r["state"] == "candidate" for r in engine.view(BASE)["actions"])


def test_rate_limit_exhaustion(engine, tmp_path):
    a = action(engine, 4, "expansion")
    approve(engine, a)
    dest = tmp_path / "remote.sqlite"
    with serve(app(dest)) as url:
        with connect(dest) as c:
            c.execute("INSERT INTO faults VALUES(?,?)", (a["id"], "rate_limit"))
        for offset in [0, 3, 8]:
            assert engine.dispatch(a["id"], BASE + offset, url) == "rate_limit"
        assert action(engine, 4, "expansion", now=BASE + 8)["state"] == "exhausted"


def test_source_authority_and_brand_isolation(engine):
    with pytest.raises(Refused, match="positive_activity_only"):
        engine.ingest(
            "cedar",
            "synthetic-0000",
            "product",
            "inactive-marker",
            1,
            BASE,
            BASE,
            "activity",
            {"active": False},
        )

    with pytest.raises(Refused, match="source_contract"):
        engine.ingest("cedar", "synthetic-0000", "product", "fake", 1, BASE, BASE, "preference", {})
    with connect(engine.path) as c:
        assert engine.facts(c, "atlas", "synthetic-0000", BASE) == {}


def test_large_reproducible(tmp_path):
    a = Lifecycle(tmp_path / "a.sqlite")
    b = Lifecycle(tmp_path / "b.sqlite")
    assert seed(a, 1200) == seed(b, 1200)


def test_analytics_late_correction_and_full_parity(engine, tmp_path):
    from signals.lifecycle_analytics import build

    engine.ingest(
        "cedar", "synthetic-0000", "crm", "outcome-a", 1, BASE, BASE, "conversion", {"converted": True}
    )
    build(engine, tmp_path / "incremental")
    engine.ingest(
        "cedar",
        "synthetic-0000",
        "crm",
        "outcome-a",
        2,
        BASE - 100,
        BASE + 10,
        "conversion",
        {"converted": False},
    )
    incremental = build(engine, tmp_path / "incremental")
    full = build(engine, tmp_path / "full", full=True)
    assert incremental == full
    assert full["models"]["fct_lifecycle_conversion"][0][-1] is False


def test_clock_only_wakeup_and_expired_coverage(tmp_path):
    e = Lifecycle(tmp_path / "later.sqlite")
    seed(e)
    assert action(e, now=BASE + 11 * DAY)["reason"] == "coverage_missing_or_expired"
    # No new source fact is required to cross quiet hours.
    assert action(e, journey="onboarding", now=BASE + 10 * 3600)["reason"] == "quiet_hours"
    assert action(e, journey="onboarding", now=BASE + 24 * 3600)["reason"] == "eligible"


def test_last_slot_race_between_two_different_actions(engine, tmp_path):
    a = action(engine)
    b = action(engine, 0, "onboarding")
    approve(engine, a)
    approve(engine, b)
    with serve(app(tmp_path / "remote.sqlite")) as url, concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda row: Lifecycle(engine.path).dispatch(row["id"], BASE, url), [a, b]))
        assert results[0] == "accepted"
        assert results[1] in {"contact_limit", "higher_priority_journey"}
    with connect(tmp_path / "remote.sqlite") as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1


def test_versioned_pause_is_effective_and_immutable(engine, tmp_path):
    a = action(engine)
    engine.register_policy(2, ["quiet"])
    engine.migrate(a["enrollment"], 2, BASE)
    engine.tick(BASE)
    fresh = action(engine)
    fresh = next(
        r
        for r in engine.view(BASE)["actions"]
        if r["person"] == "synthetic-0000" and r["journey"] == "quiet" and r["state"] == "candidate"
    )
    approve(engine, fresh)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        assert engine.dispatch(fresh["id"], BASE, url) == "journey_paused"
    with pytest.raises(Refused, match="policy_collision"):
        engine.register_policy(2, [])


def test_coverage_cannot_attest_future_observation(engine):
    with pytest.raises(Refused, match="coverage_contract"):
        engine.ingest(
            "cedar",
            "synthetic-0000",
            "product",
            "future-coverage",
            1,
            BASE,
            BASE,
            "coverage",
            {"after": BASE - DAY, "through": BASE + 1},
        )
    assert action(engine, now=BASE + 1)["reason"] == "coverage_missing_or_expired"


def test_delayed_receipt_starts_conservative_contact_window(engine, tmp_path):
    a = action(engine)
    approve(engine, a)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        assert engine.dispatch(a["id"], BASE, url, lose_ack=True) == "uncertain"
        later = BASE + 3 * DAY
        assert engine.dispatch(a["id"], later, url) == "accepted"
        row = next(r for r in engine.view(later)["actions"] if r["id"] == a["id"])
        assert row["reserved"] == later
        assert engine.dispatch(a["id"], later + 1, url) == "accepted"
        row = next(r for r in engine.view(later + 1)["actions"] if r["id"] == a["id"])
        assert row["reserved"] == later
        b = action(engine, 0, "onboarding", later + 1)
        approve(engine, b, later + 1)
        assert engine.dispatch(b["id"], later + 1, url) == "contact_limit"


def test_historical_clock_cannot_authorize_dispatch(engine, tmp_path):
    a = action(engine)
    approve(engine, a)
    engine.tick(BASE + 1)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        with pytest.raises(Refused, match="execution_clock_regression"):
            engine.dispatch(a["id"], BASE, url)
    assert engine.view(BASE)["now"] == BASE  # Read-only historical inspection is permitted.
