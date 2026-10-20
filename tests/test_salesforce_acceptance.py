"""All vendor boundaries below are local emulation, not executed Salesforce evidence."""
from contextlib import contextmanager
import json
import os
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest

from signals.contracts import digest
from signals.fixtures import AS_OF, event
from signals.salesforce_acceptance import ObservedClient, preflight, run_suite, reviewer_create_probe, permission_denied
from signals.salesforce_contract import DeliveryError, EnvironmentAttestation, MappingBook, OrganizationApproval
from signals.salesforce_delivery import _body
from signals.salesforce_dispatch import SalesforceDispatcher
from signals.seller import Workbench
from signals.harness import serve
from signals.seller_api import app
from signals.seller_fixtures import seed_workbench
from signals.store import Refused, Store
from test_salesforce_delivery import ENTRY, ORG, count
from test_salesforce_delivery import payload as sf_payload_fixture, remote as sf_remote_fixture
from test_seller import SyntheticResponder

ROOT = Path(__file__).resolve().parents[1]
payload = sf_payload_fixture
remote = sf_remote_fixture


@pytest.mark.parametrize("mode,edition,is_sandbox", [
    ("sandbox", "Enterprise Edition", True), ("developer_edition", "Developer Edition", False)])
def test_explicit_approved_environments_pass(remote, mode, edition, is_sandbox):
    inbox, state = remote
    inbox.approval = OrganizationApproval(ORG, mode, edition, True)
    state.update(edition=edition, sandbox=is_sandbox)
    assert inbox.preflight()["environment"] == mode


@pytest.mark.parametrize("mode,edition,sandbox,actual_edition,actual_org", [
    ("sandbox", "Enterprise Edition", False, "Enterprise Edition", ORG),
    ("sandbox", "Enterprise Edition", True, "Unlimited Edition", ORG),
    ("sandbox", "Enterprise Edition", True, "Enterprise Edition", "00D000000000002AAA"),
    ("developer_edition", "Developer Edition", False, "Enterprise Edition", ORG),
    ("developer_edition", "Developer Edition", False, "Developer Edition Trial", ORG),
    ("developer_edition", "Developer Edition", True, "Developer Edition", ORG),
    ("developer_edition", "Developer Edition", False, None, ORG),
    ("developer_edition", "Developer Edition", False, "Developer Edition", "00D000000000002AAA"),
    ("sandbox", "Enterprise Edition", "true", "Enterprise Edition", ORG),
])
def test_environment_mismatch_blocks_before_write(remote, mode, edition, sandbox, actual_edition, actual_org):
    inbox, state = remote
    inbox.approval = OrganizationApproval(ORG, mode, edition, True)
    state.update(edition=actual_edition, sandbox=sandbox, org=actual_org)
    with pytest.raises(DeliveryError, match="approved_environment_mismatch"):
        inbox.preflight()
    assert not inbox.ready and count(state) == 0


@pytest.mark.parametrize("mode,edition,approved", [("production", "Enterprise Edition", True),
    ("developer_edition", "Enterprise Edition", True), ("sandbox", "Enterprise Edition", False),
    ("developer_edition", "Developer Edition", False)])
def test_explicit_approval_is_required(mode, edition, approved):
    with pytest.raises(DeliveryError, match="explicit_environment_approval_required"):
        OrganizationApproval(ORG, mode, edition, approved)


@pytest.mark.parametrize("target,field,value", [
    ("account", "Brand__c", "harbour"), ("account", "Active__c", False),
    ("account", "Synthetic__c", False), ("account", "Approved_Owner__c", "005000000000002AAA"),
    ("account", "Account_Key__c", "cedar:account-0099"), ("user", "IsActive", False)])
def test_remote_mapping_must_match_before_create(remote, payload, target, field, value):
    inbox, state = remote
    state[target][field] = value
    with pytest.raises(DeliveryError):
        inbox.create(digest(payload), payload)
    assert count(state) == 0


def test_mapping_allowlist_and_immutability(remote, payload):
    inbox, state = remote
    raw = dict(ENTRY)
    book = MappingBook([raw])
    raw["user_id"] = "005000000000002AAA"
    assert book.resolve(payload)["user_id"] == ENTRY["user_id"]
    with pytest.raises(DeliveryError, match="ambiguous_mapping"):
        MappingBook([ENTRY, ENTRY])
    payload["brand"] = "harbour"
    with pytest.raises(DeliveryError, match="mapping_not_approved"):
        inbox.create(digest(payload), payload)
    assert count(state) == 0


def make_worker(tmp_path, inbox, *, attempts=4, clock=None):
    bench = Workbench(Store(tmp_path / "bench.sqlite"), SyntheticResponder(), AS_OF)
    seed_workbench(bench)
    run = bench.generate("cedar", "account-0012")
    approved = bench.approve(run["id"], bench.prepare(run["id"], digest(run))["proposal"], digest(run))
    worker = SalesforceDispatcher(bench, inbox, tmp_path / "journal.sqlite", max_attempts=attempts,
                                  **({"clock": clock} if clock else {}))
    return bench, approved, worker


def revoke(bench):
    bench.store.ingest(event("consent", {"account": "account-0012", "allowed": False, "revision": 2},
                             "native-revoked", day=31), "privacy", clock=AS_OF)


def test_receipt_reconciliation_survives_revoked_consent_and_restart(remote, tmp_path):
    inbox, state = remote
    now = [100.0]
    bench, action, worker = make_worker(tmp_path, inbox, clock=lambda: now[0])
    state["fault"] = "after_commit"
    assert worker.step(action["id"])["state"] == "retry"
    assert count(state) == 1
    revoke(bench)
    state["account"]["Active__c"] = False
    now[0] += 100
    restarted = SalesforceDispatcher(bench, inbox, tmp_path / "journal.sqlite", clock=lambda: now[0])
    assert restarted.step(action["id"])["state"] == "delivered"
    assert count(state) == 1
    assert len([r for r in state["requests"] if r[0] == "POST"]) == 1


def test_no_receipt_and_revocation_cannot_create(remote, tmp_path):
    inbox, state = remote
    bench, action, worker = make_worker(tmp_path, inbox)
    revoke(bench)
    assert worker.step(action["id"])["state"] == "blocked"
    assert count(state) == 0


def test_rejected_action_reconciles_history_but_cannot_create(remote, tmp_path):
    inbox, state = remote
    bench, action, worker = make_worker(tmp_path, inbox)
    inbox.create(action["id"], action["payload"])
    bench.reject(action["payload"]["run_id"])
    assert worker.reconcile_once(action["id"])["state"] == "delivered"
    assert count(state) == 1


def test_retry_deadline_exhaustion_and_read_only_operator_resolution(remote, tmp_path):
    inbox, state = remote
    now = [10.0]
    bench, action, worker = make_worker(tmp_path, inbox, attempts=2, clock=lambda: now[0])
    state["fault"] = "429"
    first = worker.step(action["id"])
    calls = len(state["requests"])
    assert first["state"] == "retry" and first["next_at"] >= now[0] + 3
    assert worker.step(action["id"])["attempts"] == 1
    assert len(state["requests"]) == calls
    now[0] = first["next_at"]
    assert worker.step(action["id"])["state"] == "exhausted"
    calls = len(state["requests"])
    assert worker.step(action["id"])["state"] == "exhausted"
    assert len(state["requests"]) == calls
    state["fault"] = None
    assert worker.reconcile_once(action["id"])["writes_permitted"] is False
    assert count(state) == 0 and worker.status(action["id"])["attempts"] == 2


def test_crash_after_durable_remote_ack_recovers_local_state(remote, tmp_path, monkeypatch):
    inbox, state = remote
    bench, action, worker = make_worker(tmp_path, inbox)
    original = worker._delivered

    def crash(c, key, receipt):
        original(c, key, receipt)
        raise RuntimeError("local crash before workbench commit")
    monkeypatch.setattr(worker, "_delivered", crash)
    with pytest.raises(RuntimeError):
        worker.step(action["id"])
    assert worker.status(action["id"])["state"] == "delivered"
    with bench.store.tx() as c:
        assert c.execute("SELECT state FROM seller_actions").fetchone()[0] == "approved"
    restarted = SalesforceDispatcher(bench, inbox, tmp_path / "journal.sqlite")
    assert restarted.step(action["id"])["state"] == "delivered"
    assert count(state) == 1


def test_journal_pin_and_approval_provenance_are_enforced(remote, tmp_path):
    inbox, state = remote
    bench, action, worker = make_worker(tmp_path, inbox)
    assert worker.step(action["id"])["state"] == "delivered"
    inbox.approval = OrganizationApproval("00D000000000002AAA", "sandbox", "Enterprise Edition", True)
    with pytest.raises(Refused, match="destination_changed"):
        worker.step(action["id"])
    with bench.store.tx() as c:
        c.execute("UPDATE seller_actions SET payload='{}'")
    with pytest.raises(Refused, match="approval_provenance_missing"):
        worker.reconcile_once(action["id"])
    with sqlite3.connect(tmp_path / "journal.sqlite") as c:
        with pytest.raises(sqlite3.IntegrityError, match="append only"):
            c.execute("DELETE FROM events")


@pytest.mark.parametrize("mode", ["sandbox", "developer_edition"])
@pytest.mark.parametrize("generic", [False, True])
def test_actual_acceptance_runner_over_emulated_http(remote, tmp_path, mode, generic):
    inbox, state = remote
    if mode == "developer_edition":
        state.update(sandbox=False, edition="Developer Edition")
        inbox.approval = OrganizationApproval(ORG, mode, "Developer Edition", True)
    if generic:
        state.update(reviewer_create_code="CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY", reviewer_create_status=400)
        state.update(mutation_code="CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY", mutation_status=400)
    observed = ObservedClient(inbox.client)
    inbox.client = observed
    with httpx.Client(base_url=inbox.client.client.base_url, trust_env=False,
                      headers={"Authorization": "Bearer reviewer-test-token"}) as reader, httpx.Client(
                          base_url=inbox.client.client.base_url, trust_env=False,
                          headers={"Authorization": "Bearer admin-test-token"}) as admin_client:
        reviewer = ObservedClient(reader)
        admin = ObservedClient(admin_client, read_only=True)
        assert preflight(inbox, reviewer, ENTRY["user_id"], "005000000000002AAA", admin=admin)["create_only"]
        result = run_suite(inbox, reviewer, tmp_path / "acceptance", "local-contract-only", admin=admin)
    assert result["final_exact_readback"] and result["duplicate_records"] == 1
    assert result["integration_patch_contract"]["record_unchanged"]
    assert result["integration_delete_contract"]["passed"]
    assert result["registry_write_contract"]["passed"]
    assert count(state) == 1
    check = result["reviewer_create_contract"]
    assert check["passed"] and check["effective_createable_before"] is False
    assert check["global_record_set_unchanged"] and check["probe_records_after"] == 0
    if generic:
        assert check["post_classification"] == "generic_entity_rejection_cause_unattributed"
        assert check["error_code_alone_proves_permission"] is False
    serialized = json.dumps(observed.calls + reviewer.calls)
    assert "test-only-token" not in serialized and ORG not in serialized and "Bearer" not in serialized


def test_actual_process_death_preserves_journal_and_remote_receipt(remote, tmp_path):
    inbox, state = remote
    bench, action, worker = make_worker(tmp_path, inbox)
    script = '''
import os,sys,httpx
from pathlib import Path
from signals.fixtures import AS_OF
from signals.store import Store
from signals.seller import Workbench
from signals.salesforce_delivery import SalesforceInbox
from signals.salesforce_contract import OrganizationApproval,MappingBook
from signals.salesforce_dispatch import SalesforceDispatcher
import json
root,url,key,entry,org=sys.argv[1:]
with httpx.Client(base_url=url,trust_env=False,headers={"Authorization":"Bearer test-only-token"}) as client:
    inbox=SalesforceInbox(client,OrganizationApproval(org,"sandbox","Enterprise Edition",True),MappingBook([json.loads(entry)]))
    inbox.preflight()
    bench=Workbench(Store(Path(root)/"bench.sqlite"),None,AS_OF)
    worker=SalesforceDispatcher(bench,inbox,Path(root)/"journal.sqlite")
    original=worker._delivered
    def die(c,key,receipt):
        original(c,key,receipt)
        os._exit(73)
    worker._delivered=die
    worker.step(key)
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(inbox.client.base_url),
                             action["id"], json.dumps(ENTRY), ORG], capture_output=True, timeout=30)
    assert result.returncode == 73, result.stderr.decode(errors="replace")
    assert count(state) == 1
    assert worker.step(action["id"])["state"] == "delivered"
    assert len([r for r in state["requests"] if r[0] == "POST"]) == 1


def test_browser_review_uses_bounded_dispatch_and_labels_emulation(remote, tmp_path):
    from playwright.sync_api import sync_playwright
    inbox, state = remote
    bench, action, worker = make_worker(tmp_path, inbox)
    with serve(app(bench, "local-ui-token", None, None, dispatcher=worker,
                   destination_label="Local contract test · Salesforce review")) as url:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.goto(url)
            page.locator("#token").fill("local-ui-token")
            page.get_by_role("button", name="Open workbench").click()
            page.locator("#deliver").click()
            page.locator(".receipt").wait_for()
            assert "Local contract test" in page.locator(".receipt").inner_text()
            assert "no inference" in page.locator("#proposal").inner_text()
            if target := os.environ.get("SF_CONTRACT_SCREENSHOT"):
                page.evaluate("window.scrollTo(0,0)")
                page.screenshot(path=target, full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator(".receipt").is_visible()
            browser.close()
    assert count(state) == 1


@pytest.mark.parametrize("code", ["DUPLICATE_VALUE", "REQUEST_LIMIT_EXCEEDED", "FIELD_CUSTOM_VALIDATION_EXCEPTION",
                                 "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY"])
def test_permission_probe_cannot_pass_from_unrelated_error(code):
    assert not permission_denied(httpx.Response(400, json=[{"errorCode": code}]))


@contextmanager
def observer_clients(inbox):
    with httpx.Client(base_url=inbox.client.base_url, trust_env=False,
                      headers={"Authorization": "Bearer reviewer-test-token"}) as reviewer, httpx.Client(
                      base_url=inbox.client.base_url, trust_env=False,
                      headers={"Authorization": "Bearer admin-test-token"}) as administrator:
        yield ObservedClient(reviewer), ObservedClient(administrator, read_only=True)


@pytest.mark.parametrize("status,code,passed", [
    (400, "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY", True), (403, "INSUFFICIENT_ACCESS", True),
    (400, "DUPLICATE_VALUE", False), (400, "FIELD_CUSTOM_VALIDATION_EXCEPTION", False),
    (403, "REQUEST_LIMIT_EXCEEDED", False), (401, "INVALID_SESSION_ID", False),
    (500, "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY", False)])
def test_rejected_post_requires_independent_no_create_and_no_effect(remote, payload, status, code, passed):
    inbox, state = remote
    state.update(reviewer_create_code=code, reviewer_create_status=status)
    inbox.preflight(EnvironmentAttestation(inbox.approval, "005000000000003AAA"))
    with observer_clients(inbox) as (reviewer, admin):
        result = reviewer_create_probe(inbox, reviewer, admin, dict(_body(payload, inbox.mapping), Review_Status__c="Pending"))
    assert result["passed"] is passed
    assert result["post_error_codes"] == [code] and count(state) == 0
    assert result["effective_createable_before"] is result["effective_createable_after"] is False
    assert result["error_code_alone_proves_permission"] is False


def test_rejected_post_never_masks_a_created_record(remote, payload):
    inbox, state = remote
    state["reviewer_allows_create"] = True  # adversarial platform: schema and actual behavior disagree
    inbox.preflight(EnvironmentAttestation(inbox.approval, "005000000000003AAA"))
    with observer_clients(inbox) as (reviewer, admin):
        result = reviewer_create_probe(inbox, reviewer, admin, dict(_body(payload, inbox.mapping), Review_Status__c="Pending"))
    assert result["passed"] is False and result["global_record_set_unchanged"] is False
    assert result["post_status"] == 201 and result["probe_records_after"] == 1


@pytest.mark.parametrize("fault", ["createable", "global_visibility", "key_collision"])
def test_probe_stops_before_post_if_independent_proof_unavailable(remote, payload, fault):
    inbox, state = remote
    inbox.preflight(EnvironmentAttestation(inbox.approval, "005000000000003AAA"))
    body = dict(_body(payload, inbox.mapping), Review_Status__c="Pending")
    if fault == "createable":
        state["reviewer_createable"] = True
    elif fault == "global_visibility":
        state["admin_view_all"] = False
    else:
        inbox.create(digest(payload), payload)
    before = len([r for r in state["requests"] if r[0] == "POST"])
    with observer_clients(inbox) as (reviewer, admin):
        with pytest.raises(DeliveryError):
            reviewer_create_probe(inbox, reviewer, admin, body)
    assert len([r for r in state["requests"] if r[0] == "POST"]) == before


def test_adapter_cannot_skip_environment_verification_or_reuse_a_changed_pin(remote, payload):
    inbox, state = remote
    state["sandbox"] = False
    with pytest.raises(DeliveryError, match="approved_environment_mismatch"):
        inbox.preflight()
    with pytest.raises(DeliveryError, match="approved_environment_mismatch"):
        inbox.preflight({"administrator_environment_verified": True})
    state["sandbox"] = True
    inbox.preflight(EnvironmentAttestation(inbox.approval, "005000000000003AAA"))
    inbox.approval = OrganizationApproval("00D000000000002AAA", "sandbox", "Enterprise Edition", True)
    with pytest.raises(DeliveryError, match="preflight_required"):
        inbox.create(digest(payload), payload)


def test_administrator_transport_cannot_make_writes(remote):
    inbox, state = remote
    admin = ObservedClient(inbox.client, read_only=True)
    with pytest.raises(DeliveryError, match="administrator_client_is_read_only"):
        admin.request("POST", "/should-never-be-sent")
    assert admin.calls == []


def test_long_retry_after_exhausts_without_early_retry(remote, tmp_path, monkeypatch):
    inbox, state = remote
    bench, action, worker = make_worker(tmp_path, inbox)

    def limited(key):
        raise DeliveryError("rate_limited", True, 3600)
    monkeypatch.setattr(inbox, "receipt", limited)
    assert worker.step(action["id"])["state"] == "exhausted"
    assert count(state) == 0
    with pytest.raises(ValueError, match="bounded_retry_policy"):
        SalesforceDispatcher(bench, inbox, tmp_path / "other.sqlite", ttl=86400)


def test_operator_reconciliation_error_is_sanitized(remote, tmp_path):
    from fastapi.testclient import TestClient
    inbox, state = remote
    bench, action, worker = make_worker(tmp_path, inbox)
    state["fault"] = "403"
    with TestClient(app(bench, "operator", None, None, dispatcher=worker)) as client:
        assert client.post("/api/reconcile/" + action["id"]).status_code == 401
        response = client.post("/api/reconcile/" + action["id"], headers={"Authorization": "Bearer operator"})
        assert response.status_code == 409
        assert response.json() == {"detail": "authentication_or_permission_denied"}


def test_metadata_permission_contract_and_no_automation():
    ns = {"m": "http://soap.sforce.com/2006/04/metadata"}
    main = ROOT / "salesforce/force-app/main/default"
    files = list(main.rglob("*.xml"))
    assert len(files) >= 29
    for path in files:
        ET.parse(path)
        if path.name.endswith(".field-meta.xml"):
            assert ET.parse(path).findtext("m:required", namespaces=ns) != "true"
    assert not list(main.rglob("*.cls")) and not (main / "flows").exists()
    field = ET.parse(main / "objects/Seller_Action__c/fields/Action_Key__c.field-meta.xml")
    assert field.findtext("m:externalId", namespaces=ns) == field.findtext("m:unique", namespaces=ns) == "true"
    for role in ("Integration", "Reviewer"):
        doc = ET.parse(main / f"permissionsets/Seller_Review_{role}.permissionset-meta.xml")
        perms = {p.findtext("m:object", namespaces=ns): p for p in doc.findall("m:objectPermissions", ns)}
        review = perms["Seller_Action__c"]
        assert review.findtext("m:allowDelete", namespaces=ns) == "false"
        assert review.findtext("m:modifyAllRecords", namespaces=ns) == "false"
        assert review.findtext("m:allowCreate", namespaces=ns) == str(role == "Integration").lower()
        assert review.findtext("m:allowEdit", namespaces=ns) == str(role == "Reviewer").lower()
        assert set(perms) == {"Seller_Action__c", "Synthetic_Account__c"}


@pytest.mark.parametrize("deployment", [False, True])
def test_deployment_helper_gates_the_actual_target_org(tmp_path, monkeypatch, deployment):
    import importlib.util
    spec = importlib.util.spec_from_file_location("deploy_demo", ROOT / "scripts/deploy_salesforce_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / "private-config.json"
    config.write_text(json.dumps({"approval": {"org_id": ORG, "environment": "developer_edition",
                                              "organization_type": "Developer Edition", "approved": True}}))
    args = ["deploy_demo", "--config", str(config), "--admin-alias", "test-alias"]
    if deployment:
        args.append("--deploy-approved-synthetic-metadata")
    monkeypatch.setattr(sys, "argv", args)
    calls = []

    def respond(arguments, *unused):
        calls.append(arguments)
        if "Organization" in str(arguments):
            return {"totalSize": 1, "records": [{"Id": ORG, "IsSandbox": False, "OrganizationType": "Developer Edition"}]}
        if "EntityDefinition" in str(arguments):
            return {"records": []}
        return {"success": True}
    monkeypatch.setattr(module, "sf_json", respond)
    module.main()
    deployments = [c for c in calls if "deploy" in c]
    assert len(deployments) == (2 if deployment else 1)
    assert "--dry-run" in deployments[0]


@pytest.mark.parametrize("conflict", [False, True])
def test_deployment_helper_refuses_production_or_name_conflict(tmp_path, monkeypatch, conflict):
    import importlib.util
    spec = importlib.util.spec_from_file_location("deploy_demo_negative", ROOT / "scripts/deploy_salesforce_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / "private-config.json"
    config.write_text(json.dumps({"approval": {"org_id": ORG, "environment": "developer_edition",
                                              "organization_type": "Developer Edition", "approved": True}}))
    monkeypatch.setattr(sys, "argv", ["deploy_demo", "--config", str(config), "--admin-alias", "test-alias"])
    calls = []

    def respond(arguments, *unused):
        calls.append(arguments)
        if "Organization" in str(arguments):
            return {"totalSize": 1, "records": [{"Id": ORG, "IsSandbox": False,
                        "OrganizationType": "Developer Edition" if conflict else "Enterprise Edition"}]}
        return {"records": [{"QualifiedApiName": "Seller_Action__c"}]}
    monkeypatch.setattr(module, "sf_json", respond)
    with pytest.raises((DeliveryError, RuntimeError)):
        module.main()
    assert not any("deploy" in call for call in calls)
