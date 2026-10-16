"""Continuation and mutation proof are local contract tests, never vendor execution."""
import json

import pytest

from signals.contracts import digest
from signals.salesforce_acceptance import ObservedClient, preflight, restricted_mutation_probe, resume_suite, run_suite
from signals.salesforce_contract import DeliveryError
from signals.salesforce_delivery import OBJECT
from test_salesforce_acceptance import observer_clients
from test_salesforce_delivery import ENTRY
from test_salesforce_delivery import payload as sf_payload, remote as sf_remote

payload = sf_payload
remote = sf_remote


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
@pytest.mark.parametrize("status,code,passed", [
    (400, "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY", True), (403, "INSUFFICIENT_ACCESS", True),
    (400, "FIELD_CUSTOM_VALIDATION_EXCEPTION", False), (400, "DUPLICATE_VALUE", False),
    (403, "REQUEST_LIMIT_EXCEEDED", False), (200, "", False)])
def test_mutation_rejection_requires_independent_rights_and_no_effect(remote, payload, method, status, code, passed):
    inbox, state = remote
    receipt = inbox.create(digest(payload), payload)
    state.update(mutation_status=status, mutation_code=code)
    check = restricted_mutation_probe(inbox, OBJECT, receipt["record_id"], method,
                                      body={"Subject__c": "unchanged"} if method == "PATCH" else None)
    assert check["passed"] is passed
    assert check["record_unchanged"] and check["error_code_alone_proves_permission"] is False


def test_rejected_mutation_cannot_hide_an_effect(remote, payload):
    inbox, state = remote
    receipt = inbox.create(digest(payload), payload)
    state.update(mutation_status=400, mutation_code="CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY", mutation_changes_record=True)
    check = restricted_mutation_probe(inbox, OBJECT, receipt["record_id"], "PATCH", body={"Subject__c": "unchanged"})
    assert not check["passed"] and not check["record_unchanged"]


def test_mutation_stops_before_write_if_rights_drift(remote, payload):
    inbox, state = remote
    receipt = inbox.create(digest(payload), payload)
    state["schema"]["updateable"] = True
    before = len(state["requests"])
    with pytest.raises(DeliveryError, match="restricted_mutation_permissions"):
        restricted_mutation_probe(inbox, OBJECT, receipt["record_id"], "PATCH", body={"Subject__c": "unchanged"})
    assert all(method == "GET" for method, _ in state["requests"][before:])


@pytest.mark.parametrize("fault", [None, "wrong_run", "missing_checkpoint", "changed_business_source", "missing_approval"])
def test_continuation_finishes_existing_approved_action_without_post(remote, tmp_path, monkeypatch, fault):
    import signals.salesforce_acceptance as module
    inbox, state = remote
    run_id = "local-resume-contract"
    previous = tmp_path / "old"
    previous.mkdir()
    original = module.finish_mutation_checks

    def old_error(*args):
        raise DeliveryError("integration_mutation_was_not_denied")

    with observer_clients(inbox) as (reviewer, admin):
        inbox.client = ObservedClient(inbox.client)
        preflight(inbox, reviewer, ENTRY["user_id"], "005000000000002AAA", admin=admin)
        monkeypatch.setattr(module, "finish_mutation_checks", old_error)
        with pytest.raises(DeliveryError, match="integration_mutation_was_not_denied"):
            run_suite(inbox, reviewer, previous / "private-runtime", run_id, admin=admin)
        monkeypatch.setattr(module, "finish_mutation_checks", original)
        completed = json.loads((previous / "private-runtime/acceptance-checks.json").read_text())
        prior = {"status": "FAILED", "provenance": "local_contract_emulation", "error": "integration_mutation_was_not_denied",
                 "run_id": run_id, "completed_experiments": completed, "source_sha256": module.source_fingerprints(),
                 "requests": inbox.client.calls + reviewer.calls + admin.calls}
        if fault == "wrong_run":
            prior["run_id"] = "unrelated"
        elif fault == "missing_checkpoint":
            del prior["completed_experiments"]["reviewer_create_contract"]
        elif fault == "changed_business_source":
            prior["source_sha256"]["src/signals/salesforce_delivery.py"] = "0" * 64
        elif fault == "missing_approval":
            import sqlite3
            with sqlite3.connect(previous / "private-runtime/workbench.sqlite") as c:
                c.execute("DROP TRIGGER seller_audit_no_delete")
                c.execute("DELETE FROM seller_audit WHERE action='proposal_approved'")
        source = previous / "verification.json"
        source.write_text(json.dumps(prior))
        before = len(state["requests"])
        if fault:
            with pytest.raises(DeliveryError):
                resume_suite(inbox, reviewer, tmp_path / "continuation", run_id, source,
                             admin=admin, expected_provenance="local_contract_emulation")
        else:
            result = resume_suite(inbox, reviewer, tmp_path / "continuation", run_id, source,
                                  admin=admin, expected_provenance="local_contract_emulation")
            assert result["final_exact_readback"] and result["duplicate_records"] == 1
            assert result["prior_run_status"] == "FAILED"
        assert not any(method == "POST" for method, _ in state["requests"][before:])
