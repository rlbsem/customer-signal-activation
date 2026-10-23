"""Real dbt builds and independent row-level reconciliation of lifecycle exports."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
import duckdb
from .store import Refused

ROOT = Path(__file__).resolve().parents[2]
MODELS = [
    "fct_lifecycle_action",
    "fct_lifecycle_conversion",
    "mart_lifecycle_journey",
    "fct_lifecycle_transition",
    "mart_lifecycle_daily",
    "fct_experiment_assignment",
    "fct_experiment_exposure",
    "fct_experiment_outcome",
    "mart_experiment_comparison",
]


def build(engine, workspace, full=False, as_of=None):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    database = (workspace / "lifecycle.duckdb").resolve()
    with sqlite3.connect(engine.path) as c, duckdb.connect(str(database)) as db:
        c.row_factory = sqlite3.Row
        c.execute("BEGIN")
        db.execute("BEGIN TRANSACTION")
        db.execute("CREATE SCHEMA IF NOT EXISTS raw")
        exported = {}
        from .lifecycle_experiment import TABLES

        clock = (
            as_of
            if as_of is not None
            else c.execute("SELECT value FROM execution_clock WHERE id=1").fetchone()[0]
        )
        db.execute("CREATE OR REPLACE TABLE raw.experiment_clock AS SELECT ?::BIGINT AS as_of", [clock])
        for table in ["actions", "events", "enrollment", "history"] + TABLES:
            rows = [dict(r) for r in c.execute("SELECT * FROM " + table)]
            exported[table] = rows
            info = c.execute("PRAGMA table_info(" + table + ")").fetchall()
            db.execute(
                "CREATE OR REPLACE TABLE raw."
                + table
                + "("
                + ",".join('"' + r[1] + '" ' + ("BIGINT" if r[2] == "INTEGER" else "VARCHAR") for r in info)
                + ")"
            )
            if rows:
                db.executemany(
                    "INSERT INTO raw." + table + " VALUES(" + ",".join("?" for _ in info) + ")",
                    [tuple(r.values()) for r in rows],
                )
        db.execute("COMMIT")
    env = dict(
        os.environ,
        LIFECYCLE_WAREHOUSE=str(database),
        DBT_SEND_ANONYMOUS_USAGE_STATS="false",
        DBT_LOG_PATH=str((workspace / "logs").resolve()),
    )
    command = [
        sys.executable,
        "-m",
        "dbt.cli.main",
        "build",
        "--project-dir",
        str(ROOT / "lifecycle_dbt"),
        "--profiles-dir",
        str(ROOT / "lifecycle_dbt"),
        "--target-path",
        str((workspace / "target").resolve()),
    ]
    if full:
        command.append("--full-refresh")
    result = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf8")
    (workspace / "dbt.log").write_text(result.stdout + result.stderr, encoding="utf8")
    if result.returncode:
        raise Refused("lifecycle_dbt_failed " + str(workspace / "dbt.log"))
    expected = []
    for a in exported["actions"]:
        p = json.loads(a["payload"])
        expected.append(
            (a["id"], a["state"], a["attempts"], a["reserved"], p["person"], p["brand"], p["journey"])
        )
    with duckdb.connect(str(database), read_only=True) as db:
        actual = db.execute("SELECT * FROM fct_lifecycle_action ORDER BY action_key").fetchall()
        if actual != sorted(expected):
            raise Refused("independent_action_mismatch")
        latest = {}
        for e in exported["events"]:
            if e["kind"] == "conversion":
                k = (e["brand"], e["source"], e["event_id"])
                if k not in latest or e["revision"] > latest[k]["revision"]:
                    latest[k] = e
        oracle = sorted(
            (
                e["brand"],
                e["event_id"],
                e["person"],
                e["effective"],
                e["revision"],
                json.loads(e["body"])["converted"],
            )
            for e in latest.values()
        )
        if db.execute("SELECT * FROM fct_lifecycle_conversion ORDER BY brand,event_id").fetchall() != oracle:
            raise Refused("independent_conversion_mismatch")
        aggregate = {}
        for row in expected:
            k = (row[5], row[6])
            v = aggregate.setdefault(k, [0, 0, 0, 0, 0])
            v[0] += 1
            v[1] += row[2]
            v[2] += row[1] == "accepted"
            v[3] += row[1] == "uncertain"
            v[4] += row[1] == "cancelled"
        if db.execute("SELECT * FROM mart_lifecycle_journey ORDER BY brand,journey").fetchall() != sorted(
            (*k, *v) for k, v in aggregate.items()
        ):
            raise Refused("independent_aggregate_mismatch")
        from .lifecycle_experiment import Experiments

        for experiment in exported["experiment"]:
            expected_groups = Experiments(engine).measure(experiment["id"], clock)["population"]
            for arm, expected_group in expected_groups.items():
                actual_group = db.execute(
                    "SELECT assigned,eligible,approved,accepted,conversions,mature_covered,pipeline_cents FROM mart_experiment_comparison WHERE experiment=? AND arm=?",
                    [experiment["id"], arm],
                ).fetchone()
                wanted = tuple(
                    expected_group[k]
                    for k in [
                        "assigned",
                        "eligible_at_assignment",
                        "approved",
                        "accepted",
                        "conversions",
                        "mature_covered",
                        "pipeline_cents",
                    ]
                )
                if actual_group is None and wanted[0] == 0:
                    continue
                if actual_group != wanted:
                    raise Refused("independent_experiment_mismatch")
        tables = {m: db.execute("SELECT * FROM " + m + " ORDER BY ALL").fetchall() for m in MODELS}
    return {
        "models": tables,
        "actions": len(expected),
        "conversions": len(oracle),
        "dbt": "passed",
        "oracle": "passed",
    }
