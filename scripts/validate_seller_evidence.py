"""Verify raw trace integrity and recompute every benchmark result independently of summaries."""

import argparse
import json
from pathlib import Path

from signals.contracts import digest
from signals.seller_evaluation import score, summarize


def validate(folder):
    folder = Path(folder)
    result = json.loads((folder / "evaluation.json").read_text())
    suite = json.loads((folder / "suite.json").read_text())
    cases = {c["id"]: c for c in suite["cases"]}
    expected_suite = digest({"cases": suite["cases"], "rubric": suite["rubric"], "repeats": result["repeats"]})
    if expected_suite != result["suite_hash"] or suite["suite_hash"] != expected_suite:
        raise RuntimeError("Suite digest mismatch")
    records = []
    for key, expected_hash in result["trace_hashes"].items():
        row = json.loads((folder / "traces" / (key + ".json")).read_text())
        if digest(row) != expected_hash or row["suite_hash"] != expected_suite:
            raise RuntimeError("Trace integrity failure: " + key)
        if row["input_snapshot"] != cases[row["case_id"]]["snapshot"]:
            raise RuntimeError("Trace input differs from suite: " + key)
        if "raw_proposal" in row and score(cases[row["case_id"]], row["raw_proposal"]) != row["score"]:
            raise RuntimeError("Scorer result mismatch: " + key)
        if row["arm"] != "template" and "raw_proposal" in row and row["inference"]["mode"] != "live":
            raise RuntimeError("Synthetic output in live benchmark: " + key)
        records.append(row)
    if summarize(records) != result["summary"]:
        raise RuntimeError("Recomputed summary differs")
    expected_count = len(cases) * result["repeats"] * 3
    if len(records) != expected_count or len({r["id"] for r in records}) != expected_count:
        raise RuntimeError("Benchmark coverage differs")
    return {"validated_traces": len(records), "distinct_cases": len(cases), "suite_hash": expected_suite,
            "summary_recomputed": True, "human_usefulness_review": result["human_usefulness_review"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--folder", type=Path, default=Path("docs/evidence/seller"))
    args = p.parse_args()
    print(json.dumps(validate(args.folder), indent=2))
