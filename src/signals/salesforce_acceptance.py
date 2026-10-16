"""Small native acceptance workload. Local tests inject an explicitly labelled emulator."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import time

import httpx

from .contracts import digest
from .fixtures import AS_OF
from .salesforce_contract import DeliveryError, EnvironmentAttestation, MappingBook, OrganizationApproval, sf_id
from .salesforce_delivery import API, OBJECT, SalesforceInbox, _body, _key, native_client
from .salesforce_dispatch import SalesforceDispatcher
from .seller import Workbench
from .seller_fixtures import seed_workbench
from .store import Refused, Store


class ObservedClient:
    """Allowlisted telemetry; controlled acknowledgement loss occurs after a real response."""
    def __init__(self, client, *, read_only=False):
        self.client, self.calls, self.drop_next_create = client, [], False
        self.read_only = read_only

    def request(self, method, path, **kwargs):
        if self.read_only and method.upper() != "GET":
            raise DeliveryError("administrator_client_is_read_only")
        if len(self.calls) >= 100:
            raise DeliveryError("acceptance_request_budget_exhausted")
        start = time.perf_counter()
        event = {"method": method, "resource": "review" if OBJECT in path else "other",
                 "started_utc": datetime.now(timezone.utc).isoformat()}
        try:
            response = self.client.request(method, path, **kwargs)
            event.update(status=response.status_code,
                         request_id=response.headers.get("X-SFDC-Request-Id"),
                         api_usage=response.headers.get("Sforce-Limit-Info"))
            if response.status_code >= 400:
                try:
                    body = response.json()
                    if isinstance(body, list):
                        event["error_codes"] = [e["errorCode"] for e in body if isinstance(e, dict)
                                                and isinstance(e.get("errorCode"), str)
                                                and e["errorCode"].replace("_", "").isupper()]
                except ValueError:
                    pass
            if (self.drop_next_create and method == "POST" and path == API + f"/sobjects/{OBJECT}/"
                    and response.status_code == 201):
                self.drop_next_create = False
                response.close()
                event["fault"] = "client_discarded_success_response"
                raise httpx.ReadTimeout("controlled_acknowledgement_loss")
            return response
        except httpx.TransportError:
            event["transport_outcome"] = "unknown"
            raise
        finally:
            event["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
            self.calls.append(event)


class AcceptanceResponder:
    """Handwritten source fixture, never represented as fresh inference."""
    def __init__(self, run_id):
        self.config = {"mode": "synthetic_acceptance_fixture", "run_id": run_id}

    def generate(self, snapshot):
        source = next(d for d in snapshot["documents"] if d["kind"] == "inquiry")
        return {"assessment": "The synthetic inquiry describes a workflow coordination need.",
                "action": "schedule_discovery", "claims": [{"source": source["id"], "quote": source["text"][:80]}],
                "draft": "Thank you for describing your requirements. Which workflows should we discuss?",
                "questions": ["Which workflow matters most?"], "uncertainties": ["Budget is not confirmed."]}, {
                    "mode": "synthetic_acceptance_fixture", "usage": {"total_tokens": 0}}


def identity(client, approval, expected_user):
    response = client.request("GET", "/services/oauth2/userinfo")
    if response.status_code != 200:
        raise DeliveryError("identity_endpoint_unavailable")
    try:
        value = response.json()
        if value.get("organization_id") != approval.org_id or value.get("user_id") != sf_id(expected_user, "005"):
            raise ValueError
    except (ValueError, AttributeError):
        raise DeliveryError("authenticated_identity_mismatch") from None


def reviewer_preflight(client, approval, expected_user):
    identity(client, approval, expected_user)
    # Administrator independently attests to environment before restricted checks.
    return digest(reviewer_schema(client))


def reviewer_schema(client):
    response = client.request("GET", API + f"/sobjects/{OBJECT}/describe")
    if response.status_code != 200:
        raise DeliveryError("reviewer_schema_unavailable")
    schema = response.json()
    if (schema.get("createable") is not False or schema.get("updateable") is not True
            or schema.get("deletable") is not False or schema.get("queryable") is not True):
        raise DeliveryError("reviewer_permission_contract_required")
    fields = {f["name"]: f for f in schema.get("fields", [])}
    for name in _body_fields():
        if fields.get(name, {}).get("updateable") is not False:
            raise DeliveryError("reviewer_content_fields_must_be_read_only")
    for name in ("Review_Status__c", "Reviewer_Notes__c"):
        if fields.get(name, {}).get("updateable") is not True:
            raise DeliveryError("reviewer_status_fields_required")
    return schema


def _body_fields():
    from .salesforce_delivery import FIELDS, LOOKUPS
    return [*FIELDS, *LOOKUPS]


def permission_denied(response):
    """A duplicate, validation failure or API limit is not evidence of denied permission."""
    try:
        errors = response.json()
        return (response.status_code in (400, 403) and isinstance(errors, list) and bool(errors)
                and all(isinstance(e, dict) and e.get("errorCode") in {
                    "INSUFFICIENT_ACCESS", "INSUFFICIENT_ACCESS_OR_READONLY", "INVALID_FIELD_FOR_INSERT_UPDATE"}
                    for e in errors))
    except ValueError:
        return False


def admin_environment_preflight(admin, approval):
    response = admin.request("GET", "/services/oauth2/userinfo")
    if response.status_code != 200:
        raise DeliveryError("admin_identity_endpoint_unavailable")
    try:
        admin_info = response.json()
        if (admin_info.get("organization_id") != approval.org_id
                or sf_id(admin_info.get("user_id"), "005") is None):
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise DeliveryError("admin_organization_mismatch") from None
    response = admin.request("GET", API + "/query", params={
        "q": "SELECT Id, IsSandbox, OrganizationType FROM Organization"})
    if response.status_code != 200:
        raise DeliveryError("admin_organization_query_unavailable")
    try:
        data = response.json()
        if (data.get("done") is not True or data.get("totalSize") != 1
                or len(data.get("records", [])) != 1):
            raise ValueError
        approval.verify(data["records"][0])
    except (ValueError, KeyError, TypeError, AttributeError):
        raise DeliveryError("approved_environment_mismatch") from None
    return EnvironmentAttestation(approval, admin_info["user_id"])


def preflight(inbox, reviewer, integration_user, reviewer_user, admin=None):
    inbox.ready = False
    if admin is None:
        raise DeliveryError("administrator_attestation_required")
    if integration_user == reviewer_user:
        raise DeliveryError("separate_identities_required")
    attestation = admin_environment_preflight(admin, inbox.approval)
    if attestation.observer_user_id in (integration_user, reviewer_user):
        raise DeliveryError("separate_administrator_identity_required")
    identity(inbox.client, inbox.approval, integration_user)
    reviewer_hash = reviewer_preflight(reviewer, inbox.approval, reviewer_user)
    # Never attempt unrelated business-object writes to discover an overprivileged identity.
    for client in (inbox.client, reviewer):
        registry = client.request("GET", API + "/sobjects/Synthetic_Account__c/describe")
        if registry.status_code != 200 or any(registry.json().get(k) is not False
                                               for k in ("createable", "updateable", "deletable")):
            raise DeliveryError("registry_must_be_read_only")
        r = client.request("GET", API + "/sobjects/Account/describe")
        if r.status_code not in (200, 403, 404):
            raise DeliveryError("business_object_permission_probe_failed")
        if r.status_code == 200 and any(r.json().get(k) is not False
                                       for k in ("createable", "updateable", "deletable")):
            raise DeliveryError("unrelated_business_write_permission_detected")
    result = inbox.preflight(attestation)
    result["administrator_attestation"] = attestation.public()
    result["reviewer_schema_sha256"] = reviewer_hash
    return result


def error_codes(response):
    try:
        errors = response.json()
        return [e["errorCode"] for e in errors if isinstance(e, dict) and isinstance(e.get("errorCode"), str)] if isinstance(errors, list) else []
    except ValueError:
        return []


def rejection_classification(response):
    if permission_denied(response):
        return "explicit_permission_error"
    if response.status_code == 400 and error_codes(response) == ["CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY"]:
        return "generic_entity_rejection_cause_unattributed"
    return "unexpected_response"


def restricted_mutation_probe(inbox, object_name, record_id, method, *, body=None):
    """A rejected mutation needs independent restricted rights and an unchanged readable record."""
    if object_name not in (OBJECT, "Synthetic_Account__c") or method not in ("PATCH", "DELETE"):
        raise DeliveryError("unsupported_mutation_probe")
    sf_id(record_id)
    base = f"/sobjects/{object_name}/"

    def schema():
        response = inbox._request("GET", base + "describe")
        inbox._require_success(response)
        value = inbox._json(response)
        expected = {"createable": object_name == OBJECT, "updateable": False,
                    "deletable": False, "queryable": True}
        if any(value.get(k) is not v for k, v in expected.items()):
            raise DeliveryError("restricted_mutation_permissions_not_established")
        return value

    def read():
        fields = ["Id", "OwnerId", "IsDeleted", "Name", "CreatedDate", "CreatedById", "LastModifiedDate",
                  "LastModifiedById", "SystemModstamp"]
        if object_name == OBJECT:
            fields += [*_body_fields(), "Review_Status__c", "Reviewer_Notes__c"]
        else:
            fields += ["Account_Key__c", "Brand__c", "Approved_Owner__c", "Active__c", "Synthetic__c"]
        # SOQL never updates MRU. Compare business content and mutation audit fields;
        # LastViewedDate/LastReferencedDate describe observation, not a business edit.
        response = inbox._request("GET", "/query", params={
            "q": f"SELECT {','.join(fields)} FROM {object_name} WHERE Id='{record_id}'"})
        if response.status_code != 200:
            raise DeliveryError("mutation_probe_record_not_readable")
        data = inbox._json(response)
        if (not isinstance(data, dict) or data.get("done") is not True or data.get("totalSize") != 1
                or not isinstance(data.get("records"), list) or len(data["records"]) != 1):
            raise DeliveryError("mutation_probe_record_not_readable")
        value = data["records"][0]
        if not isinstance(value, dict) or value.get("Id") != record_id:
            raise DeliveryError("mutation_probe_record_identity_mismatch")
        return value

    before_schema, before = schema(), read()
    response = inbox._request(method, base + record_id, **({"json": body} if body is not None else {}))
    after, after_schema = read(), schema()
    classification = rejection_classification(response)
    messages = []
    try:
        errors = response.json()
        if isinstance(errors, list):
            messages = [e.get("message", "") for e in errors if isinstance(e, dict)]
    except ValueError:
        pass
    # Vendor text is not published. A fixed diagnostic hint is not permission proof.
    access_hint = any("insufficient access" in str(m).lower() for m in messages)
    unchanged = digest(before) == digest(after)
    return {"passed": unchanged and classification != "unexpected_response", "operation": method,
            "effective_updateable_before": before_schema["updateable"],
            "effective_updateable_after": after_schema["updateable"],
            "effective_deletable_before": before_schema["deletable"],
            "effective_deletable_after": after_schema["deletable"],
            "schema_sha256_before": digest(before_schema), "schema_sha256_after": digest(after_schema),
            "record_sha256_before": digest(before), "record_sha256_after": digest(after), "record_unchanged": unchanged,
            "record_comparison_scope": "business_content_and_mutation_audit_fields_via_soql",
            "post_status": response.status_code, "post_error_codes": error_codes(response),
            "post_classification": classification, "error_code_alone_proves_permission": False,
            "vendor_message_sha256": digest(messages), "vendor_message_mentions_insufficient_access": access_hint}


def effect_count(inbox, key):
    _key(key)
    response = inbox._request("GET", "/query", params={
        "q": f"SELECT COUNT(Id) n FROM {OBJECT} WHERE Action_Key__c='{key}'"})
    inbox._require_success(response)
    data = inbox._json(response)
    rows = data.get("records") if isinstance(data, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or type(rows[0].get("n")) is not int or rows[0]["n"] < 0 or data.get("done") is not True):
        raise DeliveryError("record_count_not_established")
    return rows[0]["n"]


def global_record_ids(admin, attestation):
    """Use standard Id only: administrator custom-field FLS is not assumed or expanded."""
    if not isinstance(attestation, EnvironmentAttestation):
        raise DeliveryError("administrator_attestation_required")
    response = admin.request("GET", API + "/query", params={
        "q": "SELECT Profile.PermissionsViewAllData FROM User WHERE Id='" + attestation.observer_user_id + "'"})
    try:
        data = response.json()
        if (response.status_code != 200 or data.get("done") is not True or data.get("totalSize") != 1
                or data["records"][0]["Profile"]["PermissionsViewAllData"] is not True):
            raise ValueError
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise DeliveryError("global_record_visibility_not_established") from None
    response = admin.request("GET", API + "/query", params={"q": f"SELECT Id FROM {OBJECT} ORDER BY Id LIMIT 1000"})
    try:
        data = response.json()
        if (response.status_code != 200 or data.get("done") is not True or type(data.get("totalSize")) is not int
                or data["totalSize"] >= 1000 or len(data["records"]) != data["totalSize"]):
            raise ValueError
        ids = frozenset(sf_id(r["Id"]) for r in data["records"])
        if len(ids) != data["totalSize"]:
            raise ValueError
        return ids
    except (ValueError, KeyError, TypeError, AttributeError):
        raise DeliveryError("global_record_snapshot_not_established") from None


def reviewer_create_probe(inbox, reviewer, admin, body):
    """Combine independent no-Create rights and no effect with an accurately described rejection."""
    before_schema = reviewer_schema(reviewer)
    key = body["Action_Key__c"]
    before_count = effect_count(inbox, key)
    if before_count:
        raise DeliveryError("probe_key_already_exists_use_fresh_run_id")
    before_ids = global_record_ids(admin, inbox.environment_attestation)
    response = reviewer.request("POST", API + f"/sobjects/{OBJECT}/", json=body)
    after_ids = global_record_ids(admin, inbox.environment_attestation)
    after_count = effect_count(inbox, key)
    after_schema = reviewer_schema(reviewer)
    codes = error_codes(response)
    classification = rejection_classification(response)
    no_effect = before_ids == after_ids and before_count == after_count == 0
    return {"passed": no_effect and classification != "unexpected_response",
            "effective_createable_before": before_schema["createable"],
            "effective_createable_after": after_schema["createable"],
            "schema_sha256_before": digest(before_schema), "schema_sha256_after": digest(after_schema),
            "post_status": response.status_code, "post_error_codes": codes,
            "post_classification": classification, "error_code_alone_proves_permission": False,
            "probe_records_before": before_count, "probe_records_after": after_count,
            "global_record_count_before": len(before_ids), "global_record_count_after": len(after_ids),
            "global_record_set_unchanged": before_ids == after_ids,
            "global_record_set_sha256_before": digest(sorted(before_ids)),
            "global_record_set_sha256_after": digest(sorted(after_ids))}


def run_suite(inbox, reviewer, workspace, run_id, *, admin=None):
    """Call only after preflight. The caller declares native versus emulated provenance."""
    if not inbox.ready:
        raise DeliveryError("preflight_required")
    if admin is None or inbox.environment_attestation is None:
        raise DeliveryError("administrator_audit_reader_required")
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=False)
    checkpoints = {}

    def checkpoint(name, details):
        checkpoints[name] = details
        (workspace / "acceptance-checks.json").write_text(json.dumps(checkpoints, indent=2) + "\n", encoding="utf-8")
    starting_ids = global_record_ids(admin, inbox.environment_attestation)
    checkpoint("global_audit_visibility", {"passed": True, "existing_records": len(starting_ids)})
    bench = Workbench(Store(workspace / "workbench.sqlite"), AcceptanceResponder(run_id), AS_OF)
    seed_workbench(bench)
    proposal = bench.generate("cedar", "account-0012")
    action = bench.approve(proposal["id"], proposal["proposal"], digest(proposal), actor="acceptance-fixture")
    if effect_count(inbox, action["id"]):
        raise DeliveryError("action_key_already_exists_use_fresh_run_id")
    worker = SalesforceDispatcher(bench, inbox, workspace / "delivery.sqlite")
    inbox.client.drop_next_create = True
    first = worker.step(action["id"])
    if first["state"] != "retry" or first["detail"] != "transport_outcome_unknown":
        raise DeliveryError("lost_ack_experiment_not_observed")
    recovered = worker.reconcile_once(action["id"])
    if recovered["state"] != "delivered":
        raise DeliveryError("lost_ack_reconciliation_failed")
    checkpoint("lost_acknowledgement", {"passed": True, "fault": "client_discarded_real_success_response"})
    receipt = json.loads(recovered["receipt"])
    record_id = receipt["record_id"]
    if worker.step(action["id"])["receipt"] != recovered["receipt"]:
        raise DeliveryError("repeat_dispatch_changed_receipt")
    checkpoint("repeat_dispatch", {"passed": True})

    def checked(method, path, expected, **kwargs):
        response = reviewer.request(method, path, **kwargs)
        if response.status_code not in expected:
            raise DeliveryError("reviewer_experiment_failed")
        return response

    # Real duplicate POST: do not mistake a successful cached GET for unique-key enforcement.
    response = inbox._request("POST", f"/sobjects/{OBJECT}/", json=dict(
        _body(action["payload"], inbox.mapping), Review_Status__c="Pending"))
    try:
        duplicate = response.status_code == 400 and any(e["errorCode"] == "DUPLICATE_VALUE" for e in response.json())
    except (ValueError, TypeError, KeyError):
        duplicate = False
    if not duplicate:
        raise DeliveryError("native_unique_key_not_enforced")
    checkpoint("duplicate_post", {"passed": True, "post_status": response.status_code, "error_codes": error_codes(response)})
    invalid = dict(_body(action["payload"], inbox.mapping), Action_Key__c=digest({"invalid_mapping": action["id"]}),
                   Brand__c="harbour", Review_Status__c="Pending")
    response = inbox._request("POST", f"/sobjects/{OBJECT}/", json=invalid)
    try:
        rejected_mapping = response.status_code == 400 and any(
            e.get("errorCode") == "FIELD_CUSTOM_VALIDATION_EXCEPTION" for e in response.json())
    except (ValueError, TypeError, AttributeError):
        rejected_mapping = False
    if not rejected_mapping:
        raise DeliveryError("server_mapping_validation_not_established")
    checkpoint("server_mapping_validation", {"passed": True, "error_codes": error_codes(response)})
    if effect_count(inbox, action["id"]) != 1:
        raise DeliveryError("duplicate_effect_count_failed")

    path = API + f"/sobjects/{OBJECT}/" + record_id
    checked("GET", path, (200,))
    checked("PATCH", path, (204,), json={"Review_Status__c": "Reviewed", "Reviewer_Notes__c": "Synthetic internal review only."})
    if not permission_denied(checked("PATCH", path, (400,403), json={"Payload__c": "tampered"})):
        raise DeliveryError("reviewer_payload_permission_denial_not_established")
    checkpoint("reviewer_payload_write_denied", {"passed": True})
    negative = dict(action["payload"], run_id=action["payload"]["run_id"] + ":denial-probe")
    create_check = reviewer_create_probe(inbox, reviewer, admin, dict(
        _body(negative, inbox.mapping), Review_Status__c="Pending"))
    checkpoint("reviewer_create_contract", create_check)
    if create_check["passed"] is not True:
        raise DeliveryError("reviewer_create_permission_denial_not_established")
    mutation_checks = finish_mutation_checks(inbox, action, record_id, checkpoint)
    if inbox.receipt(action["id"]) != receipt:
        raise DeliveryError("post_permission_exact_readback_failed")
    # Verify the allowed review edit too; a denied mutation alone can be a false positive.
    if checked("GET", path, (200,)).json().get("Review_Status__c") != "Reviewed":
        raise DeliveryError("reviewer_status_change_not_persisted")
    checkpoint("final_exact_readback", {"passed": True, "reviewer_status": "Reviewed"})
    result = {"lost_acknowledgement": "client_discarded_real_success_response", "duplicate_records": 1,
              "duplicate_post_denied": True, "integration_update_delete_denied": True,
              "registry_write_denied": True, "reviewer_payload_write_denied": True,
              "reviewer_create_contract": create_check,
              **mutation_checks,
              "server_mapping_validation_rejected_mismatch": True,
              "reviewer_status_update_persisted": True, "final_exact_readback": True,
              "record_reference_sha256": hashlib.sha256(record_id.encode()).hexdigest(),
              "action_key": action["id"], "inference": "handwritten_acceptance_fixture_no_inference"}
    (workspace / "acceptance-result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def finish_mutation_checks(inbox, action, record_id, checkpoint):
    checks = {}
    for method in ("PATCH", "DELETE"):
        check = restricted_mutation_probe(inbox, OBJECT, record_id, method,
            body={"Subject__c": _body(action["payload"], inbox.mapping)["Subject__c"]} if method == "PATCH" else None)
        name = "integration_" + method.lower() + "_contract"
        checkpoint(name, check)
        if check["passed"] is not True:
            raise DeliveryError("integration_mutation_contract_not_established")
        checks[name] = check
    check = restricted_mutation_probe(inbox, "Synthetic_Account__c",
        inbox.mapping.resolve(action["payload"])["registry_id"], "PATCH", body={"Active__c": True})
    checkpoint("registry_write_contract", check)
    if check["passed"] is not True:
        raise DeliveryError("registry_mutation_contract_not_established")
    checks["registry_write_contract"] = check
    return checks


def source_fingerprints():
    root = Path(__file__).resolve().parents[2]
    paths = [*root.glob("src/**/*.py"), *root.glob("scripts/*.py"),
             *root.glob("salesforce/force-app/**/*.xml"), *root.glob("web/*"),
             root / "requirements.lock", root / "pyproject.toml", root / "salesforce/sfdx-project.json"]
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def resume_suite(inbox, reviewer, workspace, run_id, previous, *, admin=None, expected_provenance="native_salesforce"):
    """Finish only the remaining probes against the approved run's existing exact record; never POST."""
    previous = Path(previous)
    raw = previous.read_bytes()
    prior = json.loads(raw)
    required = {"global_audit_visibility", "lost_acknowledgement", "repeat_dispatch", "duplicate_post",
                "server_mapping_validation", "reviewer_payload_write_denied", "reviewer_create_contract"}
    completed = prior.get("completed_experiments", {})
    if (prior.get("provenance") != expected_provenance
            or prior.get("status") != "FAILED" or prior.get("error") != "integration_mutation_was_not_denied"
            or prior.get("run_id") != run_id or set(completed) != required
            or any(completed[name].get("passed") is not True for name in required)):
        raise DeliveryError("eligible_partial_acceptance_required")
    allowed_changes = {"src/signals/salesforce_acceptance.py", "src/signals/salesforce_evidence.py",
                       "scripts/run_salesforce_acceptance.py", "scripts/verify_salesforce.py"}
    fingerprints = prior.get("source_sha256", {})
    current = source_fingerprints()
    if (not fingerprints or set(current) != set(fingerprints)
            or any(current[p] != h for p, h in fingerprints.items() if p not in allowed_changes)):
        raise DeliveryError("partial_acceptance_business_sources_changed")
    # Both paths are private local inputs; the original run is opened read-only.
    runtime = previous.parent / "private-runtime"
    import sqlite3
    with sqlite3.connect((runtime / "workbench.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as c:
        rows = c.execute("SELECT id,payload,receipt FROM seller_actions WHERE state='delivered'").fetchall()
        if len(rows) == 1:
            approved = c.execute("SELECT body FROM seller_audit WHERE action='proposal_approved' AND subject=?",
                                 (rows[0][0],)).fetchall()
            run = c.execute("SELECT body FROM seller_runs WHERE id=?", (json.loads(rows[0][1])["run_id"],)).fetchone()
    if len(rows) != 1:
        raise DeliveryError("one_prior_delivered_action_required")
    key, payload, stored_receipt = rows[0]
    action = {"id": key, "payload": json.loads(payload)}
    if (digest(action["payload"]) != key or not run
            or json.loads(run[0]).get("configuration") != {"mode": "synthetic_acceptance_fixture", "run_id": run_id}
            or not any(json.loads(p[0]).get("payload_hash") == key for p in approved)):
        raise DeliveryError("partial_action_identity_mismatch")
    receipt = inbox.receipt(key)
    if receipt != json.loads(stored_receipt) or effect_count(inbox, key) != 1:
        raise DeliveryError("partial_action_exact_receipt_required")
    if admin is None:
        raise DeliveryError("administrator_audit_reader_required")
    starting_ids = global_record_ids(admin, inbox.environment_attestation)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=False)
    checkpoints = dict(completed)

    def checkpoint(name, details):
        checkpoints[name] = details
        (workspace / "acceptance-checks.json").write_text(json.dumps(checkpoints, indent=2) + "\n", encoding="utf-8")
    checkpoint("resumed_exact_receipt", {"passed": True})
    mutations = finish_mutation_checks(inbox, action, receipt["record_id"], checkpoint)
    if inbox.receipt(key) != receipt or effect_count(inbox, key) != 1:
        raise DeliveryError("post_permission_exact_readback_failed")
    response = reviewer.request("GET", API + f"/sobjects/{OBJECT}/" + receipt["record_id"])
    if response.status_code != 200 or response.json().get("Review_Status__c") != "Reviewed":
        raise DeliveryError("reviewer_status_change_not_persisted")
    if global_record_ids(admin, inbox.environment_attestation) != starting_ids:
        raise DeliveryError("continuation_global_record_set_changed")
    checkpoint("final_exact_readback", {"passed": True, "reviewer_status": "Reviewed"})
    return {"final_exact_readback": True, "reviewer_create_contract": completed["reviewer_create_contract"],
            **mutations, "duplicate_records": 1, "action_key": key,
            "resumed_prior_verification_sha256": hashlib.sha256(raw).hexdigest(),
            "prior_run_status": "FAILED", "prior_run_requests": len(prior["requests"]),
            "execution_scope": "remaining_probes_completed_existing_record_no_new_post",
            "global_record_set_unchanged": True,
            "inherited_experiments": sorted(required), "inference": "handwritten_acceptance_fixture_no_inference"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "acceptance", "dispatch", "reconcile"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", default="synthetic-acceptance-v1")
    parser.add_argument("--resume-from")
    parser.add_argument("--workbench")
    parser.add_argument("--journal")
    parser.add_argument("--action-key")
    parser.add_argument("--execute-approved-synthetic-writes", action="store_true")
    args = parser.parse_args(argv)
    if args.mode in ("acceptance", "dispatch") and not args.execute_approved_synthetic_writes:
        parser.error("explicit synthetic write authorization flag required")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    evidence = {"status": "FAILED", "provenance": "native_salesforce", "started_utc": datetime.now(timezone.utc).isoformat(),
                "checks": {}, "requests": [], "run_id": args.run_id, "python": platform.python_version(),
                "dependencies": {name: importlib.metadata.version(name) for name in
                                 ("httpx", "fastapi", "uvicorn", "pydantic")}}
    observed = []
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        approval = OrganizationApproval(**config["approval"])
        mapping = MappingBook(config["mappings"])
        with ExitStack() as stack:
            for variable in ("SF_INTEGRATION_TOKEN", "SF_REVIEWER_TOKEN", "SF_ADMIN_TOKEN"):
                token = os.environ.get(variable)
                if not token:
                    raise DeliveryError("private_environment_tokens_required")
                observed.append(ObservedClient(stack.enter_context(native_client(config["instance_url"], token)),
                                               read_only=variable == "SF_ADMIN_TOKEN"))
            inbox = SalesforceInbox(observed[0], approval, mapping)
            evidence["checks"]["preflight"] = preflight(inbox, observed[1], config["integration_user_id"], config["reviewer_user_id"], admin=observed[2])
            if args.mode == "acceptance":
                evidence["checks"]["acceptance"] = (resume_suite(inbox, observed[1], output / "private-runtime", args.run_id,
                                                                args.resume_from, admin=observed[2]) if args.resume_from else
                    run_suite(inbox, observed[1], output / "private-runtime", args.run_id, admin=observed[2]))
            elif args.mode in ("dispatch", "reconcile"):
                if not all((args.workbench, args.journal, args.action_key)):
                    raise DeliveryError("workbench_journal_action_key_required")
                bench = Workbench(Store(args.workbench), None, AS_OF)
                worker = SalesforceDispatcher(bench, inbox, args.journal)
                state = worker.step(args.action_key) if args.mode == "dispatch" else worker.reconcile_once(args.action_key)
                evidence["checks"]["delivery"] = {k: state[k] for k in ("state", "attempts", "detail") if k in state}
            evidence["status"] = ("ACTION_REQUIRED" if args.mode in ("dispatch", "reconcile")
                                  and state.get("state") != "delivered" else "PASSED")
            evidence["environment"] = approval.environment
            evidence["destination_fingerprint"] = inbox.destination_pin
    except (DeliveryError, ValueError, KeyError, OSError, httpx.HTTPError, Refused) as exc:
        # Raw vendor bodies, credential strings and local paths never enter public evidence.
        evidence["error"] = str(exc) if isinstance(exc, DeliveryError) else type(exc).__name__
    finally:
        partial = output / "private-runtime/acceptance-checks.json"
        if partial.exists():
            evidence["completed_experiments"] = json.loads(partial.read_text(encoding="utf-8"))
        evidence["requests"] = [dict(event, actor=("integration", "reviewer", "administrator")[i])
                                for i, client in enumerate(observed) for event in client.calls]
        evidence["finished_utc"] = datetime.now(timezone.utc).isoformat()
        evidence["source_sha256"] = source_fingerprints()
        (output / "verification.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "error": evidence.get("error"), "requests": len(evidence["requests"])}))
    return 0 if evidence["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
