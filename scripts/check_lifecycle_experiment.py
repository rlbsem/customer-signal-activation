"""Check current experiment source bindings, immutable historical artifacts and public links."""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from package import files

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/lifecycle-experiment"


def check():
    baseline = json.loads((EVIDENCE / "baseline.json").read_text(encoding="utf8"))
    for name, expected in baseline["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    current = EVIDENCE / "historical-receipt-fix"
    previous = json.loads((current / "previous-artifacts.json").read_text(encoding="utf8"))
    for name, expected in previous["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    original = json.loads((EVIDENCE / "execution.json").read_text(encoding="utf8"))
    for name, expected in original["source_sha256"].items():
        blob = subprocess.check_output(["git", "show", previous["revision"] + ":" + name], cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest() == expected, name
    record = json.loads((current / "execution.json").read_text(encoding="utf8"))
    for name, expected in record["source_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    for name, expected in record["screenshots"].items():
        assert hashlib.sha256((current / name).read_bytes()).hexdigest() == expected, name
    assert record["worker_exit"] == 86 and record["incremental_full_parity"]
    assert record["reference_people"] == 12 and record["large_people"] == 1200
    assert len(record["independent_receipts"]) == 2 and len(record["dbt_models"]) == 9
    assert record["corrected"]["population"]["holdout"]["accepted"] == 0
    assert sum(p["conversions"] for p in record["initial"]["population"].values()) == 4
    assert sum(p["conversions"] for p in record["corrected"]["population"].values()) == 3
    assert sum(p["pipeline_cents"] for p in record["initial"]["population"].values()) == 12500000
    assert sum(p["pipeline_cents"] for p in record["corrected"]["population"].values()) == 0
    assert record["corrected"]["commercial_incremental_revenue"] is None
    packaged = json.loads((ROOT / "package-manifest.json").read_text(encoding="utf8"))
    actual = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files()}
    assert packaged == actual, "package manifest differs from delivered files"
    links = 0
    for p in files():
        if p.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", p.read_text(encoding="utf8")):
                if not target.startswith(("http:", "https:", "mailto:", "#")):
                    links += 1
                    assert (p.parent / target.split("#")[0]).exists(), (p, target)
    print(
        json.dumps(
            {
                "preserved_historical_artifacts": len(baseline["files"]) + len(previous["files"]),
                "internal_links": links,
                "source_and_screenshot_bindings": "passed",
            }
        )
    )


if __name__ == "__main__":
    check()
