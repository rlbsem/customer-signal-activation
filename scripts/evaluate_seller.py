"""Execute actual model calls and publish inspectable, resumable benchmark records."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from signals.contracts import digest, now
from signals.fixtures import AS_OF
from signals.seller import Model, Workbench
from signals.seller_evaluation import RUBRIC, cases, score, summarize, template
from signals.seller_fixtures import seed_workbench
from signals.store import Store


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8093/v1")
    p.add_argument("--model", default="qwen3-14b")
    p.add_argument("--cases", type=int, default=60)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--development", action="store_true")
    p.add_argument("--output", type=Path, default=Path("docs/evidence/seller"))
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    bench = Workbench(Store(Path("work") / ("evaluation-dev.sqlite" if args.development else "evaluation.sqlite")),
                      as_of=AS_OF)
    seed_workbench(bench)
    manifest = list(cases(bench, args.cases, args.development))
    suite_hash = digest({"cases": manifest, "rubric": RUBRIC, "repeats": args.repeats})
    (args.output / "suite.json").write_text(json.dumps({"suite_hash": suite_hash, "rubric": RUBRIC,
        "cases": manifest, "development": args.development}, indent=2) + "\n", encoding="utf-8")
    records = []
    for arm in ("template", "simple_llm", "grounded_workflow"):
        for case in manifest:
            for repeat in range(args.repeats):
                seed = 42 + repeat
                model = Model(args.url, args.model, seed=seed, baseline=arm == "simple_llm")
                config_hash = digest({"suite_hash": suite_hash, "arm": arm, "config": model.config})
                key = f"{arm}-{case['id']}-{seed}"
                trace_path = args.output / "traces" / (key + ".json")
                trace_path.parent.mkdir(exist_ok=True)
                if trace_path.exists():
                    record = json.loads(trace_path.read_text())
                    if record["configuration_hash"] != config_hash:
                        raise RuntimeError("Stored trace configuration differs; use a fresh evidence directory")
                else:
                    record = {"id": key, "case_id": case["id"], "class": case["class"], "arm": arm,
                              "seed": seed, "suite_hash": suite_hash, "configuration_hash": config_hash,
                              "executed_at": now(), "input_snapshot": case["snapshot"]}
                    try:
                        if arm == "template":
                            raw, metadata = template(case["snapshot"]), {"mode": "deterministic_template"}
                        else:
                            raw, metadata = model.generate(case["snapshot"])
                        record.update(raw_proposal=raw, inference=metadata, score=score(case, raw))
                    except Exception as exc:
                        record.update(error=type(exc).__name__ + ": " + str(exc)[:180],
                                      score={"success": False, "checks": {},
                                             "critical_failure": case["class"] in RUBRIC["critical_classes"]})
                    trace_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
                records.append(record)
                if arm != "template":
                    print(f"{key}: {'PASS' if record['score']['success'] else 'FAIL'} "
                          f"{record.get('error', '')}", flush=True)
    summary = summarize(records)
    result = {"status": "executed", "executed_at": now(), "suite_hash": suite_hash,
              "rubric": RUBRIC, "distinct_cases": len(manifest), "repeats": args.repeats,
              "development": args.development, "summary": summary,
              "trace_hashes": {r["id"]: digest(r) for r in records},
              "human_usefulness_review": "pending",
              "cloud_cost": ("Local endpoint; provider charges, hardware and electricity are not priced."
                             if urlparse(args.url).hostname in ("127.0.0.1", "localhost", "::1")
                             else "Remote provider charges are not measured; consult provider billing.")}
    result["acceptance"] = {"mechanical_task_gate": (
        summary["grounded_workflow"]["successes"] / summary["grounded_workflow"]["samples"] >= .9
        and summary["grounded_workflow"]["critical_failures"] == 0),
        "improves_on_template": summary["grounded_workflow"]["successes"] > summary["template"]["successes"],
        "improves_on_simple_llm": summary["grounded_workflow"]["successes"] > summary["simple_llm"]["successes"]}
    (args.output / "evaluation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    table = "| Approach | Proposal checks passed | Critical quality failures | Median / p95 inference | Tokens |\n|---|---:|---:|---:|---:|\n"
    table += "".join(f"| {arm} | {r['successes']}/{r['samples']} | {r['critical_failures']} | "
                     f"{r['latency_p50']:.2f}s / {r['latency_p95']:.2f}s | {r['total_tokens']:,} |\n"
                     for arm, r in summary.items())
    (args.output / "report.md").write_text("# Executed seller workflow evaluation\n\n" + table +
        "\nThe suite has " + str(len(manifest)) + " distinct synthetic cases. Repeated runs are not independent customer samples. "
        "Cases cover discovery, ambiguity, support, suppression, contradictory requirements and hostile note instructions.\n\n"
        "The rubric tests action choice, exact quotation and required information. It does not prove general semantic "
        "support or seller usefulness. Human usefulness review is pending. No conversion or revenue uplift is claimed.\n\n"
        "All case families are known to the implementer. The delivered run is a regression comparison after "
        "source-bound citation decoding was added in response to defects in the first evaluation. "
        "The earlier failed evaluation is preserved. This is not an independently curated or blinded external benchmark.\n\n"
        "[Evaluation and acceptance results](evaluation.json) · [Cases and fixed rubric](suite.json)\n",
        encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
