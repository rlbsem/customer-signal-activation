"""Read-only continuation contracts with local fixtures; no vendor authentication."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from signals.salesforce_contract import DeliveryError
from test_integration_evidence import recorded_contract as recorded_contract_fixture, decisions

recorded_contract = recorded_contract_fixture


@pytest.fixture
def runner(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('connected_runner_contract', scripts / 'run_connected_acceptance.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checkpoint(recorded_contract):
    folder, files = recorded_contract
    prior = files['verification.json']
    prior.update(status='FAILED', error='unexpected_http_status')
    prior['source_sha256'] = {'src/signals/integration_source.py': 'a' * 64,
        'src/signals/integration_activation.py': 'b' * 64,
        'scripts/run_connected_acceptance.py': 'c' * 64}
    prior['source_sha256'].update({'src/signals/' + name + '.py': 'e' * 64
        for name in ('integration_warehouse', 'integration_snowflake', 'salesforce_contract',
                     'salesforce_delivery', 'salesforce_dispatch', 'seller', 'store')})
    files['source.json'] = files.pop('source-before.json')
    for name, value in files.items():
        (folder / name).write_text(json.dumps(value), encoding='utf-8')
    return folder, files, dict(prior['source_sha256'])


def test_resume_allows_orchestration_fix_but_preserves_business_code(runner, checkpoint):
    folder, files, current = checkpoint
    current['scripts/run_connected_acceptance.py'] = 'd' * 64
    prior, intent, source = runner.resume_inputs(folder, current)
    assert prior['status'] == 'FAILED'
    assert intent['id'] == files['intent.json']['id']
    assert source['business_hash'] == files['source.json']['business_hash']


@pytest.mark.parametrize('tamper', ['payload', 'intent_key', 'source_hash', 'source_body',
    'business_code', 'missing_business_fingerprint', 'empty_fingerprints', 'not_delivered', 'wrong_provenance'])
def test_resume_rejects_incompatible_approval_source_or_business_code(runner, checkpoint, tamper):
    folder, files, current = checkpoint
    report = files['verification.json']
    if tamper == 'payload':
        files['intent.json']['payload']['proposal']['draft'] = 'different intent'
    elif tamper == 'intent_key':
        report['checks']['intent']['action_key'] = '0' * 64
    elif tamper == 'source_hash':
        report['checks']['intent']['source_hash'] = '0' * 64
    elif tamper == 'source_body':
        files['source.json']['body']['accounts'][0]['active'] = False
    elif tamper == 'business_code':
        current['src/signals/integration_activation.py'] = 'd' * 64
    elif tamper == 'missing_business_fingerprint':
        report['source_sha256'].pop('src/signals/integration_source.py')
    elif tamper == 'empty_fingerprints':
        report['source_sha256'] = {}
    elif tamper == 'not_delivered':
        report['checks']['recovery']['restarted_state'] = 'retry'
    else:
        report['provenance'] = 'local_contract_emulator'
    for name, value in files.items():
        (folder / name).write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(DeliveryError):
        runner.resume_inputs(folder, current)


@pytest.fixture
def finish_fixture(runner, recorded_contract, monkeypatch):
    folder, files = recorded_contract
    state = {'after': deepcopy(files['source-after.json']), 'warehouse_calls': 0,
             'count': {'done': True, 'totalSize': 1, 'records': [{'n': 1}]}, 'requests': []}

    def request(method, path, **kwargs):
        assert method == 'GET'
        state['requests'].append((method, path))
        return httpx.Response(200, json=state['count'])

    def warehouse(*args, **kwargs):
        state['warehouse_calls'] += 1
        return {'status': 'PASSED', 'decisions': decisions(state['after'])}

    monkeypatch.setattr(runner, 'warehouse', warehouse)
    monkeypatch.setattr(runner, 'verify_receipt', lambda *args, **kwargs: {'independent_readback': True})
    inbox = SimpleNamespace(_require_success=lambda response: None, _json=lambda response: response.json())
    reviewer = SimpleNamespace(request=request)
    source = SimpleNamespace(extract=lambda: deepcopy(state['after']))
    record = {'status': 'FAILED', 'checks': {}}
    return state, lambda: runner.finish(SimpleNamespace(), folder, record, source, inbox, reviewer,
        files['intent.json'], files['source-before.json']), record


def test_finish_only_reads_crm_then_reconciles_complete_roundtrip(finish_fixture):
    state, finish, record = finish_fixture
    finish()
    assert record['status'] == 'PASSED'
    assert record['checks']['existing_sources_unchanged'] is True
    assert record['checks']['feedback_loop_suppressed'] is True
    assert state['warehouse_calls'] == 1
    assert all(method == 'GET' for method, _ in state['requests'])


@pytest.mark.parametrize('count', [None, [], {}, {'done': True, 'records': None},
    {'done': True, 'records': [None]}, {'done': True, 'records': [{'n': True}]},
    {'done': True, 'records': [{'n': '1'}]}, {'done': True, 'records': [{'n': 2}]},
    {'done': False, 'records': [{'n': 1}]}, {'done': True, 'records': []}])
def test_malformed_or_nonunique_independent_count_stops_before_warehouse(finish_fixture, count):
    state, finish, record = finish_fixture
    state['count'] = count
    with pytest.raises(DeliveryError, match='cardinality'):
        finish()
    assert state['warehouse_calls'] == 0 and record['status'] == 'FAILED'


@pytest.mark.parametrize('change', ['deleted_prior', 'changed_prior', 'wrong_new_action', 'changed_account'])
def test_finish_conserves_all_prior_sources_before_warehouse(finish_fixture, change):
    state, finish, record = finish_fixture
    rows = state['after']['body']['reviews']
    if change == 'deleted_prior':
        rows[0] = dict(rows[0], source_ref='9' * 64, action_key='8' * 64)
    elif change == 'changed_prior':
        rows[0]['review_status'] = 'Rejected'
    elif change == 'wrong_new_action':
        rows[-1]['action_key'] = '8' * 64
    else:
        state['after']['body']['accounts'][0]['active'] = False
    with pytest.raises(DeliveryError, match='regressed'):
        finish()
    assert state['warehouse_calls'] == 0 and record['status'] == 'FAILED'
