"""Export safety uses authored records, never represented as executed vendor results."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from signals.salesforce_contract import DeliveryError
from signals.salesforce_evidence import export_record

ROOT = Path(__file__).resolve().parents[1]


def record(tmp_path):
    source = tmp_path / "verification.json"
    data = {"provenance": "native_salesforce", "status": "FAILED", "error": "test_failure",
            "checks": {"preflight": {"environment": "developer_edition", "administrator_attestation": {
                "administrator_environment_verified": True, "organization_id": "00D000000000001AAA"}}},
            "source_sha256": {}, "requests": [{"method": "POST", "status": 400,
                "error_codes": ["CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY"], "request_id": "private-request-id",
                "Authorization": "Bearer private-test-token", "raw_response": "private-response-body"}]}
    source.write_text(json.dumps(data))
    return source, data


def test_export_preserves_failure_without_copying_private_fields(tmp_path):
    source, data = record(tmp_path)
    result = export_record(source, ROOT)
    text = json.dumps(result)
    assert result["status"] == "FAILED" and result["requests"][0]["status"] == 400
    assert result["source_fingerprint_matches_current"] is False
    assert "private-test-token" not in text and "private-response-body" not in text
    assert "00D000000000001AAA" not in text and "private-request-id" not in text
    assert result["requests"][0]["request_reference_sha256"]


@pytest.mark.parametrize("fault", ["secret", "source_path", "unreviewed_field", "false_pass"])
def test_export_refuses_unreviewed_or_false_evidence(tmp_path, fault):
    source, data = record(tmp_path)
    if fault == "secret":
        data["error"] = "Bearer private-token"
    elif fault == "source_path":
        data["source_sha256"] = {"../../private.json": "a" * 64}
    elif fault == "unreviewed_field":
        data["checks"]["config"] = {"private": "value"}
    else:
        data["status"] = "PASSED"
        data["checks"]["acceptance"] = {"final_exact_readback": True}
    source.write_text(json.dumps(data))
    with pytest.raises(DeliveryError):
        export_record(source, ROOT)


def runner_module():
    spec = importlib.util.spec_from_file_location("sf_cli_runner", ROOT / "scripts/run_salesforce_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_token_helper_uses_supported_command_and_never_prints(monkeypatch, capsys):
    module = runner_module()
    seen = []

    def fake(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"status": 0, "result": {"accessToken": "test-only-token"}}))
    monkeypatch.setattr(module.subprocess, "run", fake)
    assert module.access_token("test-sf", "demo-alias") == "test-only-token"
    assert seen[0][1:4] == ["org", "auth", "show-access-token"]
    assert capsys.readouterr().out == ""
    with pytest.raises(DeliveryError):
        module.access_token("test-sf", "alias&unsafe")


def test_cli_runner_restores_environment_and_requires_write_approval(monkeypatch):
    module = runner_module()
    monkeypatch.setenv("SF_INTEGRATION_TOKEN", "preexisting-test-token")
    monkeypatch.delenv("SF_REVIEWER_TOKEN", raising=False)
    monkeypatch.delenv("SF_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(module, "access_token", lambda *args: "temporary-test-token")
    monkeypatch.setattr(module, "accept", lambda args: 0)
    assert module.main(["preflight", "--config", "private.json", "--output", "unused", "--sf-executable", "fake"]) == 0
    assert module.os.environ["SF_INTEGRATION_TOKEN"] == "preexisting-test-token"
    assert "SF_REVIEWER_TOKEN" not in module.os.environ and "SF_ADMIN_TOKEN" not in module.os.environ
    with pytest.raises(SystemExit):
        module.main(["acceptance", "--config", "private.json", "--output", "unused", "--run-id", "fresh"])


def test_package_excludes_private_runtime_and_backups(tmp_path):
    spec = importlib.util.spec_from_file_location("package_boundary", ROOT / "scripts/package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    for name in ("README.md", "salesforce/runtime.example.json", ".local/runtime.json", ".sf/auth.json",
                 "src/module.py.bak", "work/log.txt", "private.key", "private.pem", "state.db", "state.sqlite-wal"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test data")
    assert {p.relative_to(tmp_path).as_posix() for p in module.files()} == {"README.md", "salesforce/runtime.example.json"}
