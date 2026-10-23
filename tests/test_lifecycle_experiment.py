"""Experiment adversarial acceptance uses the real lifecycle boundary and independent HTTP."""

import subprocess
import sys
import pytest
from signals.lifecycle import Lifecycle, DAY
from signals.lifecycle_experiment import Experiments, arm
from signals.lifecycle_fixtures import BASE, seed
from signals.lifecycle_destination import app
from signals.harness import serve
from signals.remote import connect
from signals.store import Refused


@pytest.fixture
def study(tmp_path):
    e = Lifecycle(tmp_path / "core.sqlite")
    seed(e)
    x = Experiments(e)
    x.register("trial-v1")
    x.assign_all("trial-v1", BASE)
    return e, x


def target(e, group):
    with connect(e.path) as c:
        return dict(
            c.execute(
                "SELECT a.*,x.arm FROM actions a JOIN experiment_assignment x ON x.enrollment=a.enrollment AND x.epoch=a.epoch WHERE x.arm=? AND x.eligibility=? LIMIT 1",
                (group, "eligible"),
            ).fetchone()
        )


def approve(e, a):
    row = next(r for r in e.view(BASE)["actions"] if r["id"] == a["id"])
    e.approve(a["id"], row["approval_hash"], BASE)


def test_assignment_stable_and_cross_journey_holdout(study, tmp_path):
    e, x = study
    first = x.measure("trial-v1", BASE)
    assert len(first["assignments"]) == 12
    # Compare stored authoritative assignment fields without derived measurement flags.
    with connect(e.path) as c:
        before = [tuple(r) for r in c.execute("SELECT * FROM experiment_assignment ORDER BY id")]
    Experiments(Lifecycle(e.path)).assign_all("trial-v1", BASE)
    with connect(e.path) as c:
        assert before == [tuple(r) for r in c.execute("SELECT * FROM experiment_assignment ORDER BY id")]
    a = target(e, "holdout")
    approve(e, a)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        assert e.dispatch(a["id"], BASE, url) == "experiment_holdout"
        with connect(e.path) as c:
            other = c.execute(
                "SELECT a.id FROM actions a JOIN enrollment n ON n.id=a.enrollment JOIN experiment_assignment x ON x.brand=n.brand AND x.person=n.person WHERE x.arm=? AND n.journey=? LIMIT 1",
                ("holdout", "onboarding"),
            ).fetchone()[0]
        assert e.dispatch(other, BASE, url) == "experiment_holdout"
    with connect(tmp_path / "remote.sqlite") as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def test_real_worker_exit_and_independent_receipt(study, tmp_path):
    e, x = study
    a = target(e, "treatment")
    approve(e, a)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        code = "from signals.lifecycle import Lifecycle;import sys;Lifecycle(sys.argv[1]).dispatch(sys.argv[2],int(sys.argv[3]),sys.argv[4],kill=True)"
        result = subprocess.run([sys.executable, "-c", code, e.path, a["id"], str(BASE), url])
        assert result.returncode == 86
        assert e.dispatch(a["id"], BASE, url) == "accepted"
        assert e.dispatch(a["id"], BASE, url) == "accepted"
        assert x.measure("trial-v1", BASE)["population"]["treatment"]["accepted"] == 1
    with connect(tmp_path / "remote.sqlite") as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1


def test_no_rerandomization_or_prior_exposure_enrollment(study, tmp_path):
    e, x = study
    x.register("trial-v2", version=2)
    with pytest.raises(Refused, match="overlapping"):
        x.assign_all("trial-v2", BASE)
    with pytest.raises(Refused, match="version_collision"):
        x.register("trial-v1", seed="different")
    with connect(e.path) as c:
        assert (
            c.execute(
                "SELECT count(*) FROM experiment_assignment WHERE experiment=?", ("trial-v2",)
            ).fetchone()[0]
            == 0
        )
    assert arm("seed", "cedar", "synthetic-0") == arm("seed", "cedar", "synthetic-0")


def test_maturity_corrections_fanout_and_missing_relationship(study):
    e, x = study
    people = [r["person"] for r in x.measure("trial-v1", BASE)["assignments"]]
    assert x.measure("trial-v1", BASE)["itt_rate_difference"] is None
    now = BASE + 7 * DAY
    for i, p in enumerate(people):
        x.coverage("coverage-" + p, 1, "cedar", p, BASE, now, now)
        if i % 3 == 0:
            e.ingest(
                "cedar", p, "crm", "conversion-" + p, 1, BASE + DAY, now, "conversion", {"converted": True}
            )
    x.value("orphan", 1, "cedar", people[0], "missing", 999999, now)
    a = x.measure("trial-v1", now)
    assert a["measurement_complete"] and a["itt_rate_difference"] is not None
    assert any(r["reason"] == "unreconciled_commercial_relationship" for r in a["exceptions"])
    p = people[0]
    x.value("legitimate-opportunity", 1, "cedar", p, "conversion-" + p, 500000, now)
    total = sum(r["pipeline_cents"] for r in x.measure("trial-v1", now)["assignments"])
    assert total == 500000
    e.ingest("cedar", p, "crm", "conversion-" + p, 2, BASE + DAY, now + 1, "conversion", {"converted": False})
    assert sum(r["pipeline_cents"] for r in x.measure("trial-v1", now + 1)["assignments"]) == 0
    assert sum(r["converted"] for r in x.measure("trial-v1", now)["assignments"]) == 4
    assert sum(r["converted"] for r in x.measure("trial-v1", now + 1)["assignments"]) == 3
    assert x.measure("trial-v1", BASE - 1)["assignments"] == []


def test_invalid_coverage_identity_and_immutable_assignment(study):
    e, x = study
    with pytest.raises(Refused, match="coverage_contract"):
        x.coverage("future", 1, "cedar", "synthetic-0000", BASE, BASE + 1, BASE)
    x.coverage("coverage", 1, "cedar", "synthetic-0000", BASE, BASE, BASE)
    with pytest.raises(Refused, match="identity_collision"):
        x.coverage("coverage", 2, "atlas", "synthetic-0000", BASE, BASE, BASE)
    with connect(e.path) as c, pytest.raises(Exception, match="immutable"):
        c.execute("UPDATE experiment_assignment SET arm='treatment'")


def test_sql_parity_and_independent_experiment_oracle(study, tmp_path):
    from signals.lifecycle_analytics import build

    e, x = study
    now = BASE + 7 * DAY
    for a in x.measure("trial-v1", BASE)["assignments"]:
        x.coverage("cov-" + a["person"], 1, a["brand"], a["person"], BASE, now, now)
    first = build(e, tmp_path / "incremental", as_of=now)
    e.ingest(
        "cedar", "synthetic-0000", "crm", "late", 1, BASE + DAY, now + 1, "conversion", {"converted": True}
    )
    inc = build(e, tmp_path / "incremental", as_of=now + 1)
    full = build(e, tmp_path / "full", full=True, as_of=now + 1)
    assert inc == full and first != inc


@pytest.mark.parametrize("change", ["preference", "commercial", "conversion"])
def test_treatment_current_authority_after_approval(study, tmp_path, change):
    e, x = study
    a = target(e, "treatment")
    approve(e, a)
    with connect(e.path) as c:
        person = c.execute("SELECT person FROM enrollment WHERE id=?", (a["enrollment"],)).fetchone()[0]
    body = {
        "preference": {"channel": "email", "purpose": "marketing", "allowed": False},
        "commercial": {"state": "trial", "opportunity": False, "owner": "changed"},
        "conversion": {"converted": True},
    }[change]
    e.ingest(
        "cedar",
        person,
        "preferences" if change == "preference" else "crm",
        person + "-" + change,
        2,
        BASE + 1,
        BASE + 1,
        change,
        body,
    )
    with serve(app(tmp_path / "remote.sqlite")) as url:
        assert e.dispatch(a["id"], BASE + 1, url) != "accepted"
    with connect(tmp_path / "remote.sqlite") as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def test_prior_contact_cannot_enter_study(tmp_path):
    e = Lifecycle(tmp_path / "core.sqlite")
    seed(e)
    a = next(
        a for a in e.view(BASE)["actions"] if a["person"] == "synthetic-0000" and a["journey"] == "quiet"
    )
    approve(e, a)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        assert e.dispatch(a["id"], BASE, url, lose_ack=True) == "uncertain"
    x = Experiments(e)
    x.register("trial-v1")
    with pytest.raises(Refused, match="prior_contact"):
        x.assign_all("trial-v1", BASE)
    with connect(e.path) as c:
        assert c.execute("SELECT count(*) FROM experiment_assignment").fetchone()[0] == 0


def test_window_edges_and_correction_before_filter(study):
    e, x = study
    p = "synthetic-0000"
    end = BASE + 7 * DAY
    x.coverage("coverage", 1, "cedar", p, BASE, end, end)
    for key, at in [("before", BASE - 1), ("start", BASE), ("end", end)]:
        e.ingest("cedar", p, "crm", key, 1, at, end, "conversion", {"converted": True})
    row = next(a for a in x.measure("trial-v1", end)["assignments"] if a["person"] == p)
    assert row["conversion_refs"] == ["start"]
    assert x.measure("trial-v1", end)["itt_rate_difference"] is None  # Other people lack coverage.
    e.ingest("cedar", p, "crm", "start", 2, end, end + 1, "conversion", {"converted": True})
    row = next(a for a in x.measure("trial-v1", end + 1)["assignments"] if a["person"] == p)
    assert not row["converted"]
    # Exact duplicate correction is idempotent; identity cannot be rebound.
    e.ingest("cedar", p, "crm", "start", 2, end, end + 1, "conversion", {"converted": True})
    with pytest.raises(Refused, match="revision_identity_changed"):
        e.ingest(
            "cedar", "synthetic-0001", "crm", "start", 3, end, end + 1, "conversion", {"converted": True}
        )


def test_other_journey_receipt_contamination_withholds_estimate(study):
    from signals.contracts import digest

    e, x = study
    end = BASE + 7 * DAY
    for a in x.measure("trial-v1", BASE)["assignments"]:
        x.coverage("coverage-" + a["person"], 1, a["brand"], a["person"], BASE, end, end)
    # Direct ledger injection models a corrupt/imported exposure; normal dispatch blocks this.
    with connect(e.path) as c:
        a = dict(
            c.execute(
                "SELECT a.* FROM actions a JOIN enrollment e ON e.id=a.enrollment JOIN experiment_assignment x ON x.brand=e.brand AND x.person=e.person WHERE x.arm='holdout' AND e.journey='onboarding' LIMIT 1"
            ).fetchone()
        )
        import json

        e.log(
            c,
            a["id"],
            BASE,
            "accepted",
            {"id": a["id"], "payload_hash": digest(json.loads(a["payload"])), "accepted": True},
        )
    result = x.measure("trial-v1", end)
    assert result["measurement_complete"]
    assert any(a["reason"] == "cross_journey_contamination" for a in result["exceptions"])
    assert result["itt_rate_difference"] is None


def test_expired_window_and_epoch_cannot_dispatch(study, tmp_path):
    e, x = study
    a = target(e, "treatment")
    approve(e, a)
    with serve(app(tmp_path / "remote.sqlite")) as url:
        assert e.dispatch(a["id"], BASE + 7 * DAY, url) == "experiment_window_closed"
    # Another fresh study checks policy migration separately from window expiration.
    e.register_policy(2)
    e.migrate(a["enrollment"], 2, BASE + 7 * DAY)
    e.tick(BASE + 7 * DAY)
    with connect(e.path) as c:
        current = c.execute(
            "SELECT id FROM actions WHERE enrollment=? AND epoch=2", (a["enrollment"],)
        ).fetchone()[0]
    with serve(app(tmp_path / "remote2.sqlite")) as url:
        assert e.dispatch(current, BASE + 7 * DAY, url) == "experiment_epoch_changed"


def test_api_read_only_and_operator_boundary(tmp_path):
    from fastapi.testclient import TestClient
    from signals.lifecycle_api import app as api

    client = TestClient(api(tmp_path / "api.sqlite", "http://127.0.0.1:1", "test-only"))
    assert client.get("/experiments").json() == []
    assert (
        client.post(
            "/operate", json={"operation": "observe_experiment"}, headers={"X-Operator": "test-only"}
        ).status_code
        == 409
    )
    assert client.post("/operate", json={"operation": "start_experiment"}).status_code == 403
    headers = {"X-Operator": "test-only"}
    assert client.post("/operate", json={"operation": "start_experiment"}, headers=headers).status_code == 200
    assert len(client.get("/experiments").json()[0]["assignments"]) == 12
    assert (
        client.post("/operate", json={"operation": "observe_experiment"}, headers=headers).status_code == 200
    )
    assert client.get("/experiments").json()[0]["measurement_complete"]
    assert (
        client.post(
            "/operate", json={"operation": "observe_experiment", "corrected": True}, headers=headers
        ).status_code
        == 200
    )
    assert sum(r["converted"] for r in client.get("/experiments").json()[0]["assignments"]) == 3


@pytest.mark.parametrize(
    "field,value", [("id", "wrong-key"), ("accepted", False), ("payload_hash", "wrong-hash")]
)
def test_invalid_independent_receipt_fails_closed(study, tmp_path, field, value):
    import json
    from signals.contracts import canonical

    e, x = study
    a = target(e, "treatment")
    approve(e, a)
    remote = tmp_path / "remote.sqlite"
    with serve(app(remote)) as url:
        assert e.dispatch(a["id"], BASE, url, lose_ack=True) == "uncertain"
        with connect(remote) as c:
            receipt = json.loads(c.execute("SELECT body FROM receipts WHERE id=?", (a["id"],)).fetchone()[0])
            receipt[field] = value
            c.execute("UPDATE receipts SET body=? WHERE id=?", (canonical(receipt), a["id"]))
        with pytest.raises(Refused, match="receipt_conflict"):
            e.dispatch(a["id"], BASE, url)
    assert x.measure("trial-v1", BASE)["population"]["treatment"]["accepted"] == 0
    assert sum(a["unresolved"] for a in x.measure("trial-v1", BASE)["assignments"]) == 1


def test_source_join_fanout_and_assignment_golden_values(study, tmp_path):
    from signals.lifecycle_analytics import build

    e, x = study
    assert arm("lifecycle-study/v1", "cedar", "synthetic-0000") == "holdout"
    assert arm("lifecycle-study/v1", "cedar", "synthetic-0007") == "treatment"
    now = BASE + 7 * DAY
    for a in x.measure("trial-v1", BASE)["assignments"]:
        x.coverage("coverage-" + a["person"], 1, a["brand"], a["person"], BASE, now, now)
    for key in ["conversion-a", "conversion-b"]:
        e.ingest("cedar", "synthetic-0000", "crm", key, 1, BASE, now, "conversion", {"converted": True})
    x.value("opportunity", 1, "cedar", "synthetic-0000", "conversion-a", 123456, now)
    x.value("opportunity", 1, "cedar", "synthetic-0000", "conversion-a", 123456, now)
    report = x.measure("trial-v1", now)
    assert sum(p["conversions"] for p in report["population"].values()) == 1
    assert sum(p["pipeline_cents"] for p in report["population"].values()) == 123456
    build(e, tmp_path / "fanout", as_of=now)
