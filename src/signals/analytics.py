import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb

from .contracts import canonical, digest
from .finance import allocations
from .store import Refused

ROOT = Path(__file__).resolve().parents[2]


def build(store, as_of, workspace):
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    with store.tx() as c:
        events = store.events(c, as_of)
        watermark = c.execute("SELECT coalesce(max(seq),0) FROM events").fetchone()[0]
    database = workspace / "candidate.duckdb"
    with duckdb.connect(str(database)) as db:
        db.execute("CREATE SCHEMA raw")
        db.execute(
            "CREATE TABLE raw.events(brand VARCHAR,event_id VARCHAR,kind VARCHAR,occurred BIGINT,body JSON)"
        )
        db.executemany(
            "INSERT INTO raw.events VALUES(?,?,?,?,?)",
            [(e["brand"], e["event_id"], e["kind"], e["occurred"], canonical(e)) for e in events],
        )
    env = dict(
        os.environ,
        SIGNALS_WAREHOUSE=str(database),
        DBT_SEND_ANONYMOUS_USAGE_STATS="false",
        DBT_LOG_PATH=str(workspace / "logs"),
    )
    command = [
        sys.executable,
        "-m",
        "dbt.cli.main",
        "build",
        "--project-dir",
        str(ROOT / "dbt"),
        "--profiles-dir",
        str(ROOT / "dbt"),
        "--target-path",
        str(workspace / "target"),
    ]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    (workspace / "dbt.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise Refused("dbt_quality_gate_failed: " + str(workspace / "dbt.log"))
    expected = allocations(events)  # Independent Python graph traversal, not loaded into dbt.
    fields = [
        "brand",
        "allocation",
        "account",
        "opportunity",
        "fulfillment",
        "invoice",
        "cents",
        "campaign",
        "touch_id",
    ]
    with duckdb.connect(str(database), read_only=True) as db:
        actual = [
            dict(zip(fields, row))
            for row in db.execute(
                "SELECT " + ",".join(fields) + " FROM fct_cash_lineage ORDER BY brand,allocation"
            ).fetchall()
        ]
        expected_rows = [{k: r[k] for k in fields} for r in expected]
        if actual != expected_rows:
            raise Refused("independent_lineage_mismatch")
        result = db.execute("SELECT * FROM mart_campaign_cash ORDER BY brand,campaign")
        names = [col[0] for col in result.description]
        metrics = [dict(zip(names, r)) for r in result.fetchall()]
    expected_metrics = []
    for brand, campaign in sorted({(r["brand"], r["campaign"]) for r in expected}):
        group = [r for r in expected if (r["brand"], r["campaign"]) == (brand, campaign)]
        invoice_values = {r["invoice"]: r["invoice_cents"] for r in group}
        expected_metrics.append(
            {
                "brand": brand,
                "campaign": campaign,
                "allocations": len(group),
                "accounts": len({r["account"] for r in group}),
                "fulfillments": len({r["fulfillment"] for r in group}),
                "cash_cents": sum(r["cents"] for r in group),
                "linked_invoice_cents": sum(invoice_values.values()),
            }
        )
    if metrics != expected_metrics:
        raise Refused("independent_metric_mismatch")
    report = {
        "as_of": as_of,
        "input_seq": watermark,
        "input_hash": digest(events),
        "cash_cents": sum(r["cents"] for r in expected),
        "allocations": len(expected),
        "campaigns": metrics,
        "lineage": actual,
        "oracle_match": True,
    }
    # Promotion only if no new event arrived during dbt; previous valid report survives failure.
    with store.tx() as c:
        if watermark != c.execute("SELECT coalesce(max(seq),0) FROM events").fetchone()[0]:
            raise Refused("inputs_changed_during_build")
        c.execute("INSERT OR REPLACE INTO publication VALUES(1,?,?)", (canonical(report), digest(report)))
    (workspace / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def published(store):
    with store.tx() as c:
        row = c.execute("SELECT * FROM publication WHERE id=1").fetchone()
        if not row:
            raise Refused("no_validated_publication")
        report = json.loads(row["body"])
        if row["hash"] != digest(report):
            raise Refused("publication_tampered")
        return report
