"""Read-only cleanup confirmation contracts, using a local injected driver."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from signals.integration_warehouse import _validate, digest
from test_integration_evidence import recorded_contract as recorded_contract_fixture

recorded_contract = recorded_contract_fixture


@pytest.fixture
def postflight(recorded_contract, monkeypatch):
    folder, files = recorded_contract
    script = Path(__file__).resolve().parents[1] / 'scripts/postflight_connected_warehouse.py'
    spec = importlib.util.spec_from_file_location('postflight_contract', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = {'before': files['source-before.json'], 'after': files['source-after.json']}
    attempt = files['verification.json']['checks']['warehouse_after']
    attempt.update(status='FAILED', error='execution_or_comparison_failed')
    attempt['native']['cleanup'].update(warehouse='suspend_failed', warehouse_error_code=None)
    attempt['loads'] = [{'input_hash': digest({k: _validate(b['body'][k], k) for k in ('accounts', 'reviews')})}
                        for b in source.values()]
    state = {'warehouse': 'SUSPENDED', 'schemas': [], 'queries': [], 'closed': False}

    def query(connection, sql):
        assert sql.startswith('SHOW '), 'postflight must never resume, write or rebuild'
        state['queries'].append(sql)
        if 'WAREHOUSES' in sql:
            return [{'state': state['warehouse']}]
        return [{'name': s} for s in state['schemas']]

    def close():
        state['closed'] = True

    monkeypatch.setattr(module, '_query', query)
    monkeypatch.setattr(module, 'SnowflakeRun', lambda *a, **kw: SimpleNamespace(
        _connect=lambda: SimpleNamespace(close=close), evidence={'queries': []}))
    source_path, attempt_path, output = folder / 'input.json', folder / 'attempt.json', folder / 'postflight.json'
    source_path.write_text(json.dumps(source))
    attempt_path.write_text(json.dumps(attempt))
    monkeypatch.setattr('sys.argv', ['postflight', '--config', 'private-placeholder', '--input', str(source_path),
                                      '--attempt', str(attempt_path), '--output', str(output)])
    return module, state, attempt, source, attempt_path, source_path, output


def test_postflight_preserves_failed_attempt_and_observes_metadata_only(postflight):
    module, state, attempt, source, original, _, output = postflight
    saved = original.read_bytes()
    module.main()
    result = json.loads(output.read_text())
    assert original.read_bytes() == saved
    assert result['executed_attempt_status'] == 'FAILED'
    assert result['native']['cleanup']['warehouse'] == 'suspend_failed'
    assert result['cleanup_postflight']['warehouse_state'] == 'SUSPENDED'
    assert len(state['queries']) == 2 and state['closed']


@pytest.mark.parametrize('fault', ['active_warehouse', 'remaining_schema', 'input_changed',
                                   'analytical_failure', 'schema_not_dropped', 'output_exists'])
def test_postflight_cannot_hide_incomplete_or_unrelated_attempt(postflight, fault):
    module, state, attempt, source, original, source_path, output = postflight
    if fault == 'active_warehouse':
        state['warehouse'] = 'STARTED'
    elif fault == 'remaining_schema':
        state['schemas'] = ['CSA_INT_OTHER']
    elif fault == 'input_changed':
        source['after']['body']['accounts'][0]['active'] = False
    elif fault == 'analytical_failure':
        attempt['checks']['complete_source_readback'] = False
    elif fault == 'schema_not_dropped':
        attempt['native']['cleanup']['schema'] = 'cleanup_failed'
    else:
        output.write_text('preserve this')
    original.write_text(json.dumps(attempt))
    source_path.write_text(json.dumps(source))
    with pytest.raises((SystemExit, ValueError)):
        module.main()
    if fault == 'output_exists':
        assert output.read_text() == 'preserve this'
    else:
        assert not output.exists()
