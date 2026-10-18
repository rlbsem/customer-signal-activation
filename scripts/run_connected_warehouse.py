"""Native bounded Snowflake lane; identical SQL is independently checked on DuckDB."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from signals.integration_snowflake import SnowflakeRun, NativeExecutionError
from signals.integration_warehouse import LocalWarehouse, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--owner-confirmed-fixture-monitor', action='store_true')
    args = parser.parse_args()
    output = Path(args.output)
    result = {'status': 'FAILED', 'provenance': 'native_snowflake',
              'started_utc': datetime.now(timezone.utc).isoformat(), 'checks': {}}
    run = None
    if output.exists():
        parser.error('choose a fresh output path; prior execution evidence is immutable')
    try:
        value = json.loads(Path(args.input).read_text())
        batches = [value['before'], value['after']] if 'before' in value else [value]
        if any(digest(b['body']) != b['business_hash'] for b in batches):
            raise ValueError('source_envelope_tampered')
        run = SnowflakeRun(args.config, monitor_owner_confirmed=args.owner_confirmed_fixture_monitor)
        with run, LocalWarehouse() as local:
            result['loads'] = []
            for index, batch in enumerate(batches):
                rows = batch['body']
                result['loads'].append(run.load(rows['accounts'], rows['reviews'], run_id=f'batch_{index}'))
                local.load(rows['accounts'], rows['reviews'], run_id=f'batch_{index}')
            decisions = run.decisions()
            if decisions != local.decisions():
                raise ValueError('local_native_result_mismatch')
            replay = run.load(batches[-1]['body']['accounts'], batches[-1]['body']['reviews'], run_id=f'batch_{len(batches)-1}')
            if replay['inserted'] != {'accounts': 0, 'reviews': 0} or decisions != run.decisions():
                raise ValueError('warehouse_replay_mismatch')
            result['checks'].update(native_duckdb_exact_comparison=True, duplicate_ingestion_no_effect=True)
            if len(batches) == 2:
                # Re-deliver earlier actual CRM state after feedback; never fabricate an older vendor version.
                run.load(batches[0]['body']['accounts'], batches[0]['body']['reviews'], run_id='late_prior_batch')
                if decisions != run.decisions():
                    raise ValueError('late_delivery_regressed_state')
                result['checks']['late_prior_actual_batch_no_regress'] = True
                # Independent build from final complete snapshot, not the incremental database.
                with LocalWarehouse() as independent:
                    independent.load(batches[1]['body']['accounts'], batches[1]['body']['reviews'])
                    if decisions != independent.decisions():
                        raise ValueError('independent_full_mismatch')
                result['checks']['independent_full_exact_comparison'] = True
            run.verify_consumer()
            result['decisions'] = decisions
            result['checks']['complete_source_readback'] = run.source_rows() == local.source_rows()
            if not result['checks']['complete_source_readback']:
                raise ValueError('source_readback_mismatch')
            run.collect_resource_usage()
        result['native'] = run.evidence
        cleanup = run.evidence['cleanup']
        if cleanup['schema'] != 'dropped' or cleanup['warehouse'] not in ('suspended', 'already_suspended'):
            raise ValueError('cleanup_incomplete')
        result['status'] = 'PASSED'
    except Exception as exc:
        result.update(error_type=type(exc).__name__,
                      error=str(exc) if isinstance(exc, NativeExecutionError) else 'execution_or_comparison_failed')
        if run is not None:
            result['native'] = run.evidence
    result['dependencies'] = {name: importlib.metadata.version(name) for name in ('snowflake-connector-python', 'duckdb')}
    result['finished_utc'] = datetime.now(timezone.utc).isoformat()
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'error': result.get('error')}))
    return 0 if result['status'] == 'PASSED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
