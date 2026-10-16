"""Allowlisted native acceptance evidence; private runtime is never copied wholesale."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .contracts import digest
from .salesforce_contract import DeliveryError

CHECK_KEYS = set("""preflight acceptance environment_pin_verified environment organization_type schema_sha256
create_only unique_external_key administrator_attestation administrator_environment_verified
organization_reference_sha256 administrator_reference_sha256 reviewer_schema_sha256
lost_acknowledgement duplicate_records duplicate_post_denied integration_update_delete_denied registry_write_denied
reviewer_payload_write_denied reviewer_create_contract server_mapping_validation_rejected_mismatch
reviewer_status_update_persisted final_exact_readback record_reference_sha256 action_key inference
passed effective_createable_before effective_createable_after schema_sha256_before schema_sha256_after
post_status post_error_codes post_classification error_code_alone_proves_permission probe_records_before
probe_records_after global_record_count_before global_record_count_after global_record_set_unchanged
global_record_set_sha256_before global_record_set_sha256_after global_audit_visibility existing_records fault
repeat_dispatch duplicate_post error_codes server_mapping_validation integration_patch_denied
integration_delete_denied reviewer_status""".split())
CHECK_KEYS.update("""integration_patch_contract integration_delete_contract registry_write_contract
operation effective_updateable_before effective_updateable_after effective_deletable_before effective_deletable_after
record_comparison_scope
record_sha256_before record_sha256_after record_unchanged vendor_message_sha256 vendor_message_mentions_insufficient_access
resumed_exact_receipt resumed_prior_verification_sha256 prior_run_status prior_run_requests execution_scope inherited_experiments
reviewer_payload_write_denied global_audit_visibility""".split())
SENSITIVE = re.compile(r"https?://|Bearer\s|force://|\b(?:00D|005)[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def clean_checks(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == "organization_id":
                result["organization_reference_sha256"] = digest(item)
                continue
            if key not in CHECK_KEYS:
                raise DeliveryError("unreviewed_evidence_field")
            result[key] = clean_checks(item)
        return result
    if isinstance(value, list):
        return [clean_checks(x) for x in value]
    if isinstance(value, str) and SENSITIVE.search(value):
        raise DeliveryError("sensitive_evidence_value")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise DeliveryError("unsupported_evidence_value")


def export_record(source, root):
    source, root = Path(source), Path(root)
    original = source.read_bytes()
    data = json.loads(original.decode("utf-8-sig"))
    if data.get("provenance") != "native_salesforce" or data.get("status") not in ("PASSED", "FAILED", "ACTION_REQUIRED"):
        raise DeliveryError("native_evidence_provenance_required")
    hashes = data.get("source_sha256", {})
    for relative, value in hashes.items():
        path = PurePosixPath(relative)
        if (path.is_absolute() or ".." in path.parts or ":" in relative
                or not re.fullmatch(r"[a-f0-9]{64}", value)):
            raise DeliveryError("invalid_evidence_source_fingerprint")
    current = [*root.glob("src/**/*.py"), *root.glob("scripts/*.py"),
               *root.glob("salesforce/force-app/**/*.xml"), *root.glob("web/*"),
               root / "requirements.lock", root / "pyproject.toml", root / "salesforce/sfdx-project.json"]
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in current if p.is_file()}
    checks = clean_checks(data.get("checks", {}))
    experiments = clean_checks(data.get("completed_experiments", {}))
    if data.get("status") == "PASSED" and "acceptance" in checks:
        accepted = checks["acceptance"]
        if (accepted.get("final_exact_readback") is not True or accepted.get("reviewer_create_contract", {}).get("passed") is not True
                or not all(x.get("passed") is True for x in experiments.values()) or not experiments
                or hashes != actual):
            raise DeliveryError("complete_current_acceptance_evidence_required")
    result = {"status": data["status"], "provenance": data["provenance"],
              "started_utc": data.get("started_utc"), "finished_utc": data.get("finished_utc"),
              "error": data.get("error"), "checks": checks, "completed_experiments": experiments,
              "source_sha256": hashes, "source_fingerprint_matches_current": hashes == actual,
              "private_record_sha256": hashlib.sha256(original).hexdigest(), "requests": []}
    for event in data.get("requests", []):
        safe = {key: event[key] for key in ("actor", "method", "resource", "started_utc", "status", "elapsed_ms",
                                           "api_usage", "error_codes", "fault", "transport_outcome") if key in event}
        if event.get("request_id"):
            safe["request_reference_sha256"] = digest(event["request_id"])
        result["requests"].append(safe)
    # Values outside checks are also inspected, including unexpected vendor/error strings.
    if SENSITIVE.search(json.dumps(result)):
        raise DeliveryError("sensitive_evidence_value")
    return result
