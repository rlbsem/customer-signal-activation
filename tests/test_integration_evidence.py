"""Offline tampering tests using handcrafted report fixtures, never native evidence."""
from copy import deepcopy
import hashlib
import json
import pytest

from signals.contracts import canonical, digest
from signals.integration_evidence import validate
from signals.integration_warehouse import LocalWarehouse


def decisions(source):
    with LocalWarehouse() as warehouse:
        warehouse.load(**source['body'])
        return warehouse.decisions()


def write_package(folder, files):
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
        (folder / name).write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def recorded_contract(tmp_path):
    account = {'source_ref': 'a' * 64, 'source_modified_at': '2026-10-17T11:00:00.000Z',
        'brand': 'cedar', 'account_key': 'account-0012', 'owner_key': 'cedar-east',
        'owner_ref': 'b' * 64, 'active': True, 'synthetic': True}
    review = {'source_ref': 'c' * 64, 'source_modified_at': '2026-10-17T11:00:00.000Z',
        'account_source_ref': account['source_ref'], 'action_key': 'd' * 64,
        'review_status': 'Reviewed', 'proposed_action': 'clarify_need'}
    body = {'accounts': [account], 'reviews': [review, dict(review, source_ref='e' * 64, action_key='f' * 64)]}
    before = {'contract': 'salesforce-review-state/v1', 'body': body, 'business_hash': digest(body),
              'source_authority': 'salesforce_synthetic_registry_and_review_state',
              'organization_ref': '1' * 64, 'observed_at': 1792238400}
    candidate = decisions(before)[0]
    text = canonical({'policy': 'review-readiness/v1', 'source_hash': before['business_hash'], 'decision': candidate})
    payload = {'run_id': 'contract-only-run', 'brand': 'cedar', 'account': 'account-0012', 'owner': 'cedar-east',
        'evidence_hash': '2' * 64, 'proposal': {'action': 'clarify_need',
        'draft': 'Synthetic internal review only; this is an offline validator fixture.',
        'claims': [{'source': 'warehouse-' + digest(candidate), 'quote': text[:400]}]}}
    intent = {'id': digest(payload), 'payload': payload, 'state': 'approved'}
    after = deepcopy(before)
    after['body']['reviews'].append(dict(review, source_ref='0' * 64, action_key=intent['id'],
        source_modified_at='2026-10-17T12:00:00.000Z', review_status='Pending'))
    after['business_hash'] = digest(after['body'])

    def stage(source, prefix):
        return {'status': 'PASSED', 'provenance': 'native_snowflake', 'decisions': decisions(source),
            'checks': {'native_duckdb_exact_comparison': True, 'duplicate_ingestion_no_effect': True,
                'complete_source_readback': True, 'late_prior_actual_batch_no_regress': True,
                'independent_full_exact_comparison': True},
            'native': {'cleanup': {'schema': 'dropped', 'warehouse': 'suspended', 'gate': 'released'},
                'exclusive_gate': 'acquired',
                'consumer': {'candidate_readback': 'passed', 'raw_read_denials': 3,
                    'separate_identity': True, 'view_grants': ['SELECT'], 'user_role_grants_checked': True},
                'warehouse': {'size': 'XSMALL', 'auto_suspend_seconds': 60, 'max_clusters': 1,
                    'query_acceleration': False, 'credit_quota': 1},
                'queries': [{'query_id': prefix + str(i), 'status': 'succeeded' if i == 0 else 'failed',
                    **({'error_code': 2003} if i else {})} for i in range(4)]}}

    source_file = tmp_path / 'source.py'
    source_file.write_text('# offline validator contract fixture\n')
    report = {'status': 'PASSED', 'provenance': 'native_connected_salesforce_snowflake',
        'source_sha256': {'source.py': hashlib.sha256(source_file.read_bytes()).hexdigest()},
        'checks': {'preflight': {'environment_pin_verified': True, 'create_only': True},
            'intent': {'action_key': intent['id'], 'decision_hash': candidate['decision_hash'],
                       'source_hash': before['business_hash']},
            'independent_readback': {'action_key': intent['id'], 'payload_hash': intent['id'],
                                     'independent_readback': True},
            'independent_action_count': 1,
            'recovery': {'first_state': 'retry', 'restarted_state': 'delivered',
                         'repeated_state': 'delivered', 'post_requests': 1},
            'existing_sources_unchanged': True, 'feedback_loop_suppressed': True,
            'warehouse_before': stage(before, 'contract-before-'),
            'warehouse_after': stage(after, 'contract-after-')},
        'requests': [{'method': 'POST', 'actor': 'integration', 'status': 201,
                      'fault': 'client_discarded_success_response'},
                     {'method': 'GET', 'actor': 'reviewer', 'status': 200}]}
    files = {'verification.json': report, 'source-before.json': before,
             'source-after.json': after, 'intent.json': intent}
    folder = tmp_path / 'package'
    write_package(folder, files)
    return folder, files


def test_offline_contract_fixture_passes_without_claiming_new_execution(recorded_contract):
    folder, _ = recorded_contract
    result = validate(folder, root=folder.parent)
    assert result['status'] == 'recorded_native_evidence_checked_offline'
    assert result['new_vendor_execution'] is False


@pytest.mark.parametrize('tamper', ['duplicate_post', 'missing_fault', 'failed_native',
    'no_native_queries', 'consumer_raw_access', 'source_fingerprint', 'forged_decision'])
def test_incomplete_or_contradictory_evidence_cannot_pass(recorded_contract, tamper):
    folder, files = recorded_contract
    report = files['verification.json']
    if tamper == 'duplicate_post':
        report['requests'].append(deepcopy(report['requests'][0]))
    elif tamper == 'missing_fault':
        report['requests'][0].pop('fault')
    elif tamper == 'failed_native':
        report['checks']['warehouse_before']['status'] = 'FAILED'
    elif tamper == 'no_native_queries':
        report['checks']['warehouse_after']['native']['queries'] = []
    elif tamper == 'consumer_raw_access':
        report['checks']['warehouse_after']['native']['consumer']['raw_read_denials'] = 2
    elif tamper == 'source_fingerprint':
        report['source_sha256']['source.py'] = '0' * 64
    else:
        report['checks']['warehouse_before']['decisions'][0]['review_count'] += 1
    write_package(folder, files)
    with pytest.raises((AssertionError, ValueError, KeyError)):
        validate(folder, root=folder.parent)


def test_deleted_old_review_replaced_by_unrelated_new_review_cannot_pass(recorded_contract):
    folder, files = recorded_contract
    after = files['source-after.json']
    pending = after['body']['reviews'][-1]
    retained = after['body']['reviews'][0]
    replacement = dict(retained, source_ref='9' * 64, action_key='8' * 64)
    # Keep the total count and one Pending row; all surviving old rows are unchanged.
    after['body']['reviews'] = [pending, retained, replacement]
    after['business_hash'] = digest(after['body'])
    files['verification.json']['checks']['warehouse_after']['decisions'] = decisions(after)
    write_package(folder, files)
    with pytest.raises((AssertionError, ValueError)):
        validate(folder)


def test_intent_source_hash_must_bind_the_actual_extraction(recorded_contract):
    folder, files = recorded_contract
    files['verification.json']['checks']['intent']['source_hash'] = '0' * 64
    write_package(folder, files)
    with pytest.raises((AssertionError, ValueError)):
        validate(folder)


def test_source_fingerprint_inventory_cannot_be_empty(recorded_contract):
    folder, files = recorded_contract
    files['verification.json']['source_sha256'] = {}
    write_package(folder, files)
    with pytest.raises((AssertionError, ValueError)):
        validate(folder, root=folder.parent)
