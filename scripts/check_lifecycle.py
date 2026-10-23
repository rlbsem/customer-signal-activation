"""Verify prior artifact preservation, lifecycle source links and public package inputs."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
baseline = json.loads((ROOT / "docs/evidence/lifecycle/baseline.json").read_text(encoding="utf8"))
for name, h in baseline["files"].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == h, name
for file in [ROOT / "docs/lifecycle.md", ROOT / "docs/evidence/lifecycle/README.md"]:
    for link in re.findall(r"\]\(([^)]+)\)", file.read_text(encoding="utf8")):
        if not link.startswith(("http:", "https:", "#")):
            assert (file.parent / link.split("#")[0]).is_file(), link
record = json.loads((ROOT / "docs/evidence/lifecycle/execution.json").read_text(encoding="utf8"))
assert (
    record["reference_people"] == 12 and record["large_people"] == 1200 and record["incremental_full_parity"]
)
for name, h in record["source_sha256"].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == h, name
for name, h in record["screenshots"].items():
    assert hashlib.sha256((ROOT / "docs/evidence/lifecycle" / name).read_bytes()).hexdigest() == h
for p in list((ROOT / "src/signals").glob("lifecycle*.py")) + [ROOT / "web/lifecycle.html"]:
    data = p.read_text(encoding="utf8")
    assert "BEGIN RSA PRIVATE KEY" not in data and "AKIA" not in data
print("443 prior evidence/image hashes, lifecycle links and screenshot fingerprints verified")
