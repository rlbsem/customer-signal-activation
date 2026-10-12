import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from demo import run
from package import files, manifest
from validate_seller_evidence import validate as validate_seller

ROOT = Path(__file__).resolve().parents[1]


def verify():
    os.chdir(ROOT)
    work = ROOT / "work" / ("verification-" + uuid.uuid4().hex)
    work.mkdir(parents=True)
    evidence = ROOT / "docs" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SIGNALS_SCREENSHOT=str(ROOT / "docs/images/browser-proof.png"))
    commands = [
        [sys.executable, "-m", "pip", "check"],
        [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--basetemp",
            str(work / "pytest"),
            "-o",
            "cache_dir=" + str(work / "pytest-cache"),
            "--junitxml",
            str(work / "tests.xml"),
        ],
    ]
    checks = []
    for command in commands:
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        (work / (f"command-{len(checks)}.log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        print(result.stdout, flush=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        checks.append({"command": command[1:4], "returncode": result.returncode})
    a = run(work / "demo-a", evidence)
    b = run(work / "demo-b", work / "evidence-b")
    if a != b:
        raise RuntimeError("deterministic demonstration mismatch")
    dbt_result = json.loads((work / "demo-a/warehouse/target/run_results.json").read_text(encoding="utf-8"))
    dbt_manifest = json.loads((work / "demo-a/warehouse/target/manifest.json").read_text(encoding="utf-8"))
    dbt_evidence = {
        "dbt_version": dbt_result["metadata"]["dbt_version"],
        "elapsed_seconds": dbt_result["elapsed_time"],
        "results": [
            {
                "node": r["unique_id"],
                "status": r["status"],
                "execution_seconds": r["execution_time"],
                "depends_on": dbt_manifest["nodes"][r["unique_id"]]["depends_on"]["nodes"],
            }
            for r in dbt_result["results"]
        ],
    }
    (evidence / "dbt-results.json").write_text(json.dumps(dbt_evidence, indent=2) + "\n", encoding="utf-8")
    (evidence / "tests.xml").write_bytes((work / "tests.xml").read_bytes())
    stages = {
        stage: sum(d["stage"] == stage for d in a["decisions"])
        for stage in ("qualified", "nurture", "customer", "hold")
    }
    summary = (
        f"The executed synthetic demonstration has **{a['accounts']} accounts and {a['source_events']:,} source events**. "
        f"It produces **${a['commercial']['cash_cents'] / 100:,.2f} allocated cash**, "
        f"{a['remote']['contacts']} reconciled CRM projections and {a['remote']['conversions']} eligible cash-conversion records. "
        f"Decisions include {stages['qualified']} qualified, {stages['nurture']} nurture, "
        f"{stages['customer']} customer and {stages['hold']} hold outcomes. "
        "Open qualified opportunities do not manufacture cash; exclusions remain inspectable."
    )
    readme = ROOT / "README.md"
    readme.write_text(
        re.sub(
            r"<!-- executed-result:start -->.*?<!-- executed-result:end -->",
            "<!-- executed-result:start -->\n" + summary + "\n<!-- executed-result:end -->",
            readme.read_text(encoding="utf-8"),
            flags=re.S,
        ),
        encoding="utf-8",
    )
    broken, count = [], 0
    for path in files():
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith(("http:", "https:", "mailto:", "#")):
                continue
            count += 1
            resolved = (path.parent / target.split("#")[0]).resolve()
            if not resolved.exists() and resolved != evidence / "verification.json":
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    if broken:
        raise RuntimeError("Broken links: " + str(broken))
    suite = ET.parse(work / "tests.xml").getroot().find("testsuite")
    record = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tests": {k: suite.attrib[k] for k in ("tests", "failures", "errors", "skipped")},
        "commands": checks,
        "demo_equal": True,
        "internal_links_checked": count,
        "hosted_ci": "not run for this local delivery",
        "source_sha256": {},
    }
    seller_evidence = evidence / "seller"
    if (seller_evidence / "evaluation.json").exists():
        record["seller_evaluation"] = validate_seller(seller_evidence)
    for p in files():
        rel = p.relative_to(ROOT).as_posix()
        if not rel.startswith("docs/evidence/") and p.suffix not in (".png", ".jpg"):
            record["source_sha256"][rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    (evidence / "verification.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    manifest()
    print(json.dumps(record["tests"]))


if __name__ == "__main__":
    verify()
