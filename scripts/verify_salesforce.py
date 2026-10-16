"""Local candidate verification; preserves all previously archived evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from demo import run
from package import files, manifest
from validate_seller_evidence import validate

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", default="docs/evidence/salesforce-local/reviewer-create-fix")
    args = parser.parse_args()
    os.chdir(ROOT)
    output = (ROOT / args.evidence_dir).resolve()
    if (output / "verification.json").exists():
        raise RuntimeError("Choose a fresh evidence directory; prior verification records are preserved")
    output.mkdir(parents=True, exist_ok=True)
    work = ROOT / "work" / ("salesforce-verification-" + uuid.uuid4().hex)
    work.mkdir(parents=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1",
               SF_CONTRACT_SCREENSHOT=str(output / "contract-review.png"))
    env.pop("SIGNALS_SCREENSHOT", None)
    env.pop("SELLER_SCREENSHOT", None)
    baseline = json.loads((ROOT / "docs/evidence/salesforce-local/reviewer-create-fix/existing-evidence-sha256.json").read_text())
    for path, expected in baseline.items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError("Prior evidence changed: " + path)

    def source_hashes():
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files()
                if not p.relative_to(ROOT).as_posix().startswith("docs/evidence/")
                and p.suffix not in (".png", ".jpg")}
    tested_sources = source_hashes()
    commands = [[sys.executable, "-m", "pip", "check"],
                [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
                [sys.executable, "-m", "pytest", "-q", "-o", "faulthandler_timeout=60", "--basetemp", str(work / "pytest"),
                 "--junitxml", str(work / "tests.xml")]]
    checks = []
    for number, command in enumerate(commands):
        result = subprocess.run(command, env=env, text=True, encoding="utf-8", capture_output=True, timeout=900)
        (work / f"check-{number}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        print(result.stdout, flush=True)
        if result.returncode:
            raise RuntimeError("Local check failed; see private work logs")
        checks.append({"command": command[1:4], "returncode": 0})
    a = run(work / "demo-a", work / "evidence-a")
    b = run(work / "demo-b", work / "evidence-b")
    if a != b:
        raise RuntimeError("Independent demo mismatch")
    archived = validate(ROOT / "docs/evidence/seller")
    tree = ET.parse(work / "tests.xml")
    for element in tree.iter():
        if "hostname" in element.attrib:
            element.set("hostname", "local-windows-host")
    tree.write(output / "tests.xml", encoding="utf-8", xml_declaration=True)
    suite = tree.getroot().find("testsuite")
    local = [c for c in suite.findall("testcase") if "test_salesforce" in c.get("classname", "")]
    paths_checked = 0
    for path in files():
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith(("https:", "http:", "mailto:", "#")):
                continue
            resolved = (path.parent / target.split("#")[0]).resolve()
            if not resolved.exists() and resolved != output / "verification.json":
                raise RuntimeError(f"Broken local link in {path.relative_to(ROOT)}: {target}")
            paths_checked += 1
    for path, expected in baseline.items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError("Prior evidence changed during verification: " + path)
    record = {"provenance": "local_contract_emulation_not_salesforce", "executed_utc": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "tests": {k: suite.get(k) for k in ("tests", "failures", "errors", "skipped", "time")},
              "salesforce_contract_cases": len(local), "commands": checks,
              "deterministic_demos_equal": True, "demo_accounts": a["accounts"], "demo_cash_cents": a["commercial"]["cash_cents"],
              "prior_evidence_files_preserved": len(baseline), "archived_seller_validation": archived,
              "preservation_baseline": "existing local evidence captured before this finishing review",
              "upstream_baseline_differences": "docs/evidence/salesforce-local/reviewer-create-fix/baseline-provenance.json",
              "markdown_paths_checked": paths_checked, "native_salesforce": "not_executed",
              "metadata_deployment": "outside_local_verifier_scope", "hosted_ci": "not_run",
              "fresh_inference": "not_executed", "source_sha256": {}}
    if source_hashes() != tested_sources:
        raise RuntimeError("Source changed during verification; rerun on the final candidate")
    record["source_sha256"] = tested_sources
    (output / "verification.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    manifest()
    print(json.dumps({"tests": record["tests"], "salesforce_contract_cases": len(local),
                      "prior_evidence_preserved": len(baseline), "native_salesforce": "not_executed"}))


if __name__ == "__main__":
    main()
