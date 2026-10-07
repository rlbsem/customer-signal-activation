import argparse
import json
from pathlib import Path

from signals.analytics import build
from signals.contracts import digest
from signals.decision import plan
from signals.finance import plan_conversions
from signals.fixtures import AS_OF, seed, sources
from signals.harness import serve
from signals.remote import app, connect
from signals.reconcile import reconcile
from signals.store import Store
from signals.worker import deliver_one


def run(workspace, evidence, count=120):
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    evidence = Path(evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    store = Store(workspace / "signals.sqlite")
    seed(store, count)
    decisions = plan(store, AS_OF)
    financial = plan_conversions(store, AS_OF)
    with serve(app(workspace / "remote.sqlite")) as url:
        # One real lost-acknowledgement experiment within the business run.
        with store.tx() as c:
            fault_key = c.execute("SELECT id FROM outbox ORDER BY rowid LIMIT 1").fetchone()[0]
        with connect(workspace / "remote.sqlite") as c:
            c.execute("INSERT INTO faults VALUES(?,?)", (fault_key, "timeout_after_commit"))
        for clock in (AS_OF, AS_OF + 2, AS_OF + 6, AS_OF + 14):
            while deliver_one(store, url, clock, timeout=0.15):
                pass
        reconciliation = reconcile(store, url)
        assert reconciliation["matched"]
    report = build(store, AS_OF, workspace / "warehouse")
    with connect(workspace / "remote.sqlite") as c:
        remote_counts = {
            t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("contacts", "conversions", "receipts")
        }
    evidence_body = {
        "source_hash": digest(list(sources(count))),
        "source_events": store.status()["events"],
        "accounts": count,
        "decisions": decisions,
        "delivery": store.status(),
        "remote": remote_counts,
        "reconciliation": reconciliation,
        "commercial": report,
        "conversion_exclusions": [
            {"allocation": r["allocation"], "reason": r["ineligible_reason"]}
            for r in financial
            if r["ineligible_reason"]
        ],
    }
    (evidence / "demo.json").write_text(json.dumps(evidence_body, indent=2) + "\n", encoding="utf-8")
    (evidence / "report.md").write_text(
        "# Executed signal-to-cash review\n\n"
        f"{count} synthetic accounts; {evidence_body['source_events']:,} retained source events. "
        f"Collected cash: CAD {report['cash_cents'] / 100:,.2f} across {report['allocations']} allocations.\n\n"
        f"{remote_counts['contacts']} CRM projections and {remote_counts['conversions']} cash conversion receipts "
        "were persisted by the separate HTTP destination. Other allocations retain explicit eligibility exclusions.\n\n"
        "Attribution is first observed campaign touch before the won opportunity. It is descriptive, not causal. "
        "The invoice measure covers invoices linked to collected cash; it is not all company billing.\n\n"
        "| Brand | Campaign | Accounts | Fulfillments | Linked invoice CAD | Allocated cash CAD |\n|---|---|---:|---:|---:|---:|\n"
        + "".join(
            f"| {r['brand']} | {r['campaign']} | {r['accounts']} | {r['fulfillments']} | "
            f"{r['linked_invoice_cents'] / 100:,.2f} | {r['cash_cents'] / 100:,.2f} |\n"
            for r in report["campaigns"]
        )
        + "\n[Complete decisions, exclusions and event-level lineage](demo.json).\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "accounts": count,
                "events": evidence_body["source_events"],
                "cash_cents": report["cash_cents"],
                "remote": remote_counts,
            }
        )
    )
    return evidence_body


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--evidence", default="docs/evidence")
    parser.add_argument("--accounts", type=int, default=120)
    args = parser.parse_args()
    run(args.workspace, args.evidence, args.accounts)
