"""Independent seller-operation grains, separate from commercial cash attribution."""

import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb

from .store import Refused

ROOT = Path(__file__).resolve().parents[2]


def build(workbench, workspace):
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    database = workspace / "seller.duckdb"
    with workbench.store.tx() as c:
        runs = [(r["id"], r["body"]) for r in c.execute("SELECT * FROM seller_runs")]
        actions = [(r["id"], r["run_id"], r["state"], r["attempts"], r["payload"], r["receipt"])
                   for r in c.execute("SELECT * FROM seller_actions")]
        audits = [(r["seq"], r["action"], r["subject"], r["occurred"], r["body"])
                  for r in c.execute("SELECT * FROM seller_audit")]
    with duckdb.connect(str(database)) as db:
        db.execute("CREATE SCHEMA raw")
        db.execute("CREATE TABLE raw.runs(id VARCHAR,body JSON)")
        db.execute("CREATE TABLE raw.actions(id VARCHAR,run_id VARCHAR,state VARCHAR,attempts INTEGER,payload JSON,receipt JSON)")
        db.execute("CREATE TABLE raw.audit(seq BIGINT,action VARCHAR,subject VARCHAR,occurred BIGINT,body JSON)")
        if runs:
            db.executemany("INSERT INTO raw.runs VALUES(?,?)", runs)
        if actions:
            db.executemany("INSERT INTO raw.actions VALUES(?,?,?,?,?,?)", actions)
        if audits:
            db.executemany("INSERT INTO raw.audit VALUES(?,?,?,?,?)", audits)
    env = dict(os.environ, SELLER_WAREHOUSE=str(database), DBT_SEND_ANONYMOUS_USAGE_STATS="false",
               DBT_LOG_PATH=str(workspace / "logs"))
    result = subprocess.run([sys.executable, "-m", "dbt.cli.main", "build", "--project-dir", str(ROOT / "seller_dbt"),
                             "--profiles-dir", str(ROOT / "seller_dbt"), "--target-path", str(workspace / "target")],
                            env=env, text=True, capture_output=True)
    (workspace / "dbt.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise Refused("seller_dbt_quality_gate_failed")
    with duckdb.connect(str(database), read_only=True) as db:
        cursor = db.execute("SELECT * FROM mart_seller_workflow ORDER BY mode,model")
        names = [r[0] for r in cursor.description]
        summary = [dict(zip(names, row)) for row in cursor.fetchall()]
        if db.execute("SELECT count(*) FROM fct_seller_runs").fetchone()[0] != len(runs):
            raise Refused("seller_run_grain_mismatch")
        if db.execute("SELECT count(*) FROM fct_seller_actions").fetchone()[0] != len(actions):
            raise Refused("seller_action_grain_mismatch")
    return {"runs": len(runs), "actions": len(actions), "audit_events": len(audits), "summary": summary,
            "dbt_results": json.loads((workspace / "target/run_results.json").read_text())}
