"""Read-only confirmation after successful analytics but uncertain warehouse suspension."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from signals.integration_snowflake import SnowflakeRun
from signals.integration_warehouse import LocalWarehouse, _query, _validate, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--input', required=True)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error('preserve_prior_evidence')
    original = Path(args.attempt).read_bytes()
    attempt = json.loads(original)
    source = json.loads(Path(args.input).read_text())
    batches = [source['before'], source['after']]
    if (attempt['status'] != 'FAILED' or attempt['native']['cleanup']['schema'] != 'dropped'
            or attempt['native']['cleanup']['warehouse'] != 'suspend_failed'
            or attempt['native']['cleanup'].get('warehouse_error_code') is not None
            or not all(attempt['checks'].get(k) is True for k in ('native_duckdb_exact_comparison',
                        'duplicate_ingestion_no_effect', 'late_prior_actual_batch_no_regress',
                        'independent_full_exact_comparison', 'complete_source_readback'))):
        parser.error('only_completed_analytical_attempt_with_unconfirmed_cleanup_is_eligible')
    expected_hashes = [digest({kind: _validate(b['body'][kind], kind) for kind in ('accounts', 'reviews')})
                       for b in batches]
    if [r['input_hash'] for r in attempt['loads']] != expected_hashes:
        parser.error('checkpoint_input_mismatch')
    with LocalWarehouse() as local:
        for batch in batches:
            local.load(**batch['body'])
        if attempt['decisions'] != local.decisions():
            parser.error('checkpoint_decision_mismatch')
    run = SnowflakeRun(args.config, monitor_owner_confirmed=True)
    connection = run._connect()
    try:
        warehouses = _query(connection, "SHOW WAREHOUSES LIKE 'RMP_WH'")
        if len(warehouses) != 1 or warehouses[0].get('state') != 'SUSPENDED':
            raise ValueError('warehouse_not_suspended_no_resume_permitted')
        schemas = _query(connection, "SHOW SCHEMAS IN DATABASE REVENUE_METRICS_DEMO")
        if any(r['name'].startswith('CSA_INT_') for r in schemas):
            raise ValueError('integration_schema_still_present')
        postflight = {'status': 'PASSED', 'observed_utc': datetime.now(timezone.utc).isoformat(),
                      'warehouse_state': 'SUSPENDED', 'integration_schemas_remaining': 0,
                      'operations': 'metadata_only_no_resume_no_ddl_no_dml', 'queries': run.evidence['queries']}
        result = dict(attempt, status='PASSED_AFTER_READ_ONLY_POSTFLIGHT',
                      executed_attempt_status=attempt['status'], cleanup_postflight=postflight,
                      prior_attempt_sha256=hashlib.sha256(original).hexdigest())
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    finally:
        connection.close()
    print(json.dumps({'status': result['status'], 'postflight_queries': len(postflight['queries'])}))


if __name__ == '__main__':
    main()
