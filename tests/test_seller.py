"""Software invariants use explicitly synthetic responders, never claimed as inference."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from signals.contracts import digest
from signals.fixtures import AS_OF, event
from signals.harness import serve
from signals.seller import Workbench, task_destination, validate_proposal
from signals.seller_api import app
from signals.seller_fixtures import seed_workbench
from signals.store import Refused, Store


class SyntheticResponder:
    config = {"mode": "synthetic_software_test", "model": "handwritten-responder", "prompt_hash": "fixture-v1"}

    def __init__(self):
        self.calls = 0

    def generate(self, snapshot):
        self.calls += 1
        source = next(d for d in snapshot["documents"] if d["kind"] == "inquiry")
        return {"assessment": "The inquiry describes a workflow coordination need.",
                "action": "schedule_discovery", "claims": [{"source": source["id"], "quote": source["text"][:80]}],
                "draft": "Thank you for describing your requirements. Which workflows should we discuss?",
                "questions": ["Which workflow matters most?"], "uncertainties": ["Budget is not confirmed."]}, {
                    "mode": "synthetic_software_test", "usage": {"total_tokens": 0}, "latency_seconds": 0}


@pytest.fixture
def bench(tmp_path):
    workbench = Workbench(Store(tmp_path / "seller.sqlite"), SyntheticResponder(), AS_OF)
    seed_workbench(workbench)
    return workbench


def run(bench):
    return bench.generate("cedar", "account-0012")


def approved(bench):
    record = run(bench)
    return bench.approve(record["id"], record["proposal"], digest(record))


def test_brand_account_scope_and_authority(bench):
    context = bench.context("cedar", "account-0012")
    assert context["decision"]["stage"] == "qualified"
    assert context["decision"]["owner"] == "cedar-east"
    assert all(d.get("account", "account-0012") == "account-0012" for d in context["documents"])
    assert not any("Customer support" in d["title"] for d in context["documents"])


def test_document_identity_and_freshness(bench):
    raw = {"id": "stale-note", "brand": "cedar", "account": "account-0012", "revision": 1,
           "title": "Stale note", "kind": "call_note", "occurred_at": "2026-01-01T12:00:00Z", "text": "Old details."}
    bench.document(raw)
    assert bench.document(raw) == raw
    with pytest.raises(Refused, match="identity_conflict"):
        bench.document(dict(raw, text="Changed details."))
    snapshot = bench.context("cedar", "account-0012")
    assert snapshot["excluded_documents"] == [{"id": "stale-note", "reason": "outside_30_day_window"}]
    assert "stale-note" not in {d["id"] for d in snapshot["documents"]}


@pytest.mark.parametrize("change", ["invented_source", "invented_quote", "extra_field"])
def test_unverifiable_model_output_refused(bench, change):
    snapshot = bench.context("cedar", "account-0012")
    proposal, _ = bench.model.generate(snapshot)
    if change == "invented_source":
        proposal["claims"][0]["source"] = "other-account"
    elif change == "invented_quote":
        proposal["claims"][0]["quote"] = "A guaranteed fifty percent revenue increase."
    else:
        proposal["execute_now"] = True
    with pytest.raises(ValueError):
        validate_proposal(proposal, snapshot)


def test_concurrent_cache_calls_model_once(bench):
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: run(bench), range(4)))
    assert bench.model.calls == 1
    assert len({r["id"] for r in records}) == 1
    assert sum(r["cached"] for r in records) == 3


def test_provider_failure_visible_not_a_fake_result(bench):
    def unavailable(snapshot):
        raise httpx.ConnectError("provider unavailable")
    bench.model.generate = unavailable
    record = run(bench)
    assert record["status"] == "failed"
    assert "proposal" not in record
    assert bench.overview()["actions"] == []


def test_changed_evidence_invalidates_approval(bench):
    record = run(bench)
    bench.document({"id": "new-note", "brand": "cedar", "account": "account-0012", "revision": 1,
                    "title": "New note", "kind": "call_note", "occurred_at": "2026-03-31T12:00:00Z",
                    "text": "The requirement has changed."})
    with pytest.raises(Refused, match="evidence_changed"):
        bench.approve(record["id"], record["proposal"], digest(record))


def test_review_edits_bound_to_immutable_approved_content(bench):
    record = run(bench)
    proposal = dict(record["proposal"], draft="Reviewed by the seller. Which workflow should we discuss first?")
    action = bench.approve(record["id"], proposal, digest(record))
    assert action["payload"]["proposal"]["draft"] == proposal["draft"]
    with pytest.raises(Refused, match="immutable"):
        bench.approve(record["id"], record["proposal"], digest(record))
    with pytest.raises(Refused, match="run_changed"):
        bench.approve(record["id"], proposal, "wrong-hash")


def test_suppression_blocks_even_a_bad_model_proposal(bench):
    record = bench.generate("cedar", "account-0004")
    assert record["proposal"]["action"] == "schedule_discovery"  # deliberately unsafe software fixture
    with pytest.raises(Refused, match="policy_blocks"):
        bench.approve(record["id"], record["proposal"], digest(record))


def test_reject_is_terminal(bench):
    record = run(bench)
    bench.reject(record["id"])
    with pytest.raises(Refused, match="proposal_rejected"):
        bench.approve(record["id"], record["proposal"], digest(record))


def test_real_http_receipt_recovery_after_remote_commit(bench, tmp_path):
    action = approved(bench)
    path = tmp_path / "tasks.sqlite"
    with serve(task_destination(path, "destination-test-token")) as url:
        # Simulate local process dying after remote commit, before recording acknowledgement.
        r = httpx.post(url + "/seller/tasks/" + action["id"], json=action["payload"],
                       headers={"Authorization": "Bearer destination-test-token"}, trust_env=False)
        assert r.status_code == 200
        assert bench.deliver(action["id"], url, "destination-test-token") == r.json()
        assert bench.deliver(action["id"], url, "destination-test-token") == r.json()
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT count(*) FROM seller_tasks").fetchone()[0] == 1
    assert bench.overview()["actions"][0]["attempts"] == 1


def test_revocation_between_approval_and_dispatch(bench, tmp_path):
    action = approved(bench)
    bench.store.ingest(event("consent", {"account": "account-0012", "allowed": False, "revision": 2},
                             "revoke-seller", day=31), "privacy", clock=AS_OF)
    with serve(task_destination(tmp_path / "tasks.sqlite", "test-token")) as url:
        with pytest.raises(Refused, match="evidence_changed"):
            bench.deliver(action["id"], url, "test-token")
    with sqlite3.connect(tmp_path / "tasks.sqlite") as c:
        assert c.execute("SELECT count(*) FROM seller_tasks").fetchone()[0] == 0


def test_retry_preserves_approval_and_records_attempt(bench):
    action = approved(bench)
    result = bench.deliver(action["id"], "http://127.0.0.1:1", "token", timeout=0.1)
    assert result["state"] == "retry"
    assert bench.overview()["actions"][0]["attempts"] == 1


def test_audit_is_append_only(bench):
    run(bench)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with bench.store.tx() as c:
            c.execute("DELETE FROM seller_audit")


def test_operator_auth_origin_and_cached_approval(bench):
    with TestClient(app(bench, "operator-token", "http://127.0.0.1:1", "dest-token")) as client:
        assert client.get("/api/overview").status_code == 401
        assert client.post("/api/login", json={"token": "wrong"}).status_code == 401
        assert client.post("/api/login", json={"token": "operator-token"}).status_code == 200
        assert client.post("/api/generate/cedar/account-0012", json={},
                           headers={"Origin": "https://hostile.example"}).status_code == 403
        client.post("/api/generate/cedar/account-0012", json={})
        record = client.post("/api/generate/cedar/account-0012", json={}).json()
        assert record["run"]["cached"]
        assert client.post("/api/approve/" + record["run"]["id"], json={
            "proposal": record["run"]["proposal"], "review_hash": record["review_hash"]}).status_code == 200
        html = client.get("/").text
        assert "operator-token" not in html and "dest-token" not in html
        assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]


def test_actual_seller_browser_review_and_destination(bench, tmp_path):
    from playwright.sync_api import sync_playwright

    with serve(task_destination(tmp_path / "crm.sqlite", "destination")) as destination:
        with serve(app(bench, "browser-login", destination, "destination")) as url:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                page.goto(url)
                page.locator("#token").fill("browser-login")
                page.get_by_role("button", name="Open workbench").click()
                page.get_by_role("button", name="Generate live brief").click()
                page.locator("#draft").wait_for()
                page.locator("#draft").fill("A reviewed seller response: which workflow should we discuss first?")
                page.get_by_role("button", name="Approve CRM task").click()
                page.get_by_role("button", name="Deliver approved task").click()
                page.get_by_text("Task persisted in the synthetic CRM").wait_for()
                assert page.locator(".receipt").count() == 1
                assert page.locator("#draft").is_disabled()
                browser.close()
    with sqlite3.connect(tmp_path / "crm.sqlite") as c:
        payload = json.loads(c.execute("SELECT body FROM seller_tasks").fetchone()[0])
        assert payload["proposal"]["draft"].startswith("A reviewed seller response")


def test_operational_dbt_grains_do_not_fan_out_repeated_approvals(bench, tmp_path):
    from signals.seller_analytics import build
    record = run(bench)
    bench.approve(record["id"], record["proposal"], digest(record))
    bench.approve(record["id"], record["proposal"], digest(record))
    result = build(bench, tmp_path / "warehouse")
    assert result["runs"] == 1 and result["actions"] == 1
    metrics = result["summary"][0]
    assert metrics["generated_runs"] == 1 and metrics["approved_actions"] == 1
    assert metrics["delivered_actions"] == 0 and metrics["total_tokens"] == 0
    assert all(r["status"] in ("success", "pass") for r in result["dbt_results"]["results"])


def test_evaluator_rejects_wrong_action_and_quote(bench):
    from signals.seller_evaluation import cases, score, template
    case = next(cases(bench, 1))
    proposal = template(case["snapshot"])
    # Exact quotation alone does not count as useful task completion.
    assert not score(case, proposal)["success"]
    proposal["claims"][0]["quote"] = "Fabricated customer requirement."
    assert not score(case, proposal)["checks"]["exact_source_quotes"]
    proposal["action"] = "no_action"
    assert not score(case, proposal)["checks"]["expected_action"]


def test_no_eval_expectations_enter_model_context(bench):
    from signals.seller_evaluation import cases
    case = next(cases(bench, 1))
    assert not {"expected_action", "required_any", "forbidden", "class"}.intersection(case["snapshot"])
