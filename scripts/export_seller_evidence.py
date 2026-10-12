"""Export real application records and independently built operational metrics."""

import argparse
import json
from pathlib import Path

from signals.fixtures import AS_OF
from signals.seller import Workbench
from signals.seller_analytics import build
from signals.store import Store


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--warehouse", type=Path, required=True)
    args = p.parse_args()
    bench = Workbench(Store(args.workspace / "seller.sqlite"), as_of=AS_OF)
    result = build(bench, args.warehouse)
    record = bench.overview()
    record["status"] = "executed_application_record"
    record["execution_scope"] = "Browser operated by engineering agent; real local model and synthetic HTTP CRM."
    record["human_usefulness_review"] = "pending"
    path = Path("docs/evidence/seller")
    path.mkdir(parents=True, exist_ok=True)
    (path / "application.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (path / "operations.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runs": result["runs"], "actions": result["actions"], "summary": result["summary"]}, indent=2))


if __name__ == "__main__":
    main()
