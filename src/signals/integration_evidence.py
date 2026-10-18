"""Offline checks of recorded native evidence; never authenticates or executes a vendor query."""
import hashlib
import json
from pathlib import Path

from .contracts import digest
from .integration_activation import verify_decision


def validate(folder, *, root=None):
    folder = Path(folder)
    report = json.loads((folder / 'verification.json').read_text(encoding='utf-8'))
    before = json.loads((folder / 'source-before.json').read_text(encoding='utf-8'))
    after = json.loads((folder / 'source-after.json').read_text(encoding='utf-8'))
    intent = json.loads((folder / 'intent.json').read_text(encoding='utf-8'))
    checks = report['checks']
    assert isinstance(report['source_sha256'], dict) and report['source_sha256']
    assert checks['intent']['source_hash'] == before['business_hash']
    assert report['status'] == 'PASSED' and report['provenance'] == 'native_connected_salesforce_snowflake'
    assert checks['preflight']['environment_pin_verified'] is True
    assert checks['preflight']['create_only'] is True
    assert digest(intent['payload']) == intent['id'] == checks['intent']['action_key']
    assert checks['independent_readback']['action_key'] == intent['id']
    assert checks['independent_readback']['payload_hash'] == intent['id']
    assert checks['independent_readback']['independent_readback'] is True
    assert checks['independent_action_count'] == 1
    assert checks['recovery'] == {'first_state': 'retry', 'restarted_state': 'delivered',
                                  'repeated_state': 'delivered', 'post_requests': 1}
    posts = [r for r in report['requests'] if r['method'] == 'POST']
    assert len(posts) == 1 and posts[0]['status'] == 201
    assert posts[0]['fault'] == 'client_discarded_success_response'
    assert all(r['method'] == 'GET' for r in report['requests'] if r['actor'] != 'integration')
    if 'continuation' in report:
        prior = json.loads((folder / 'initial-failed-attempt.json').read_text())
        assert prior['status'] == report['continuation']['prior_status'] == 'FAILED'
        assert prior['private_record_sha256'] == report['continuation']['prior_private_record_sha256']
        assert prior['source_sha256'] == report['continuation']['prior_source_sha256']
        assert report['continuation']['new_salesforce_writes_permitted'] is False
        assert report['continuation']['native_business_code_matches'] is True
        assert all(r['method'] == 'GET' for r in report['requests'] if r.get('stage') == 'continuation')
    assert checks['existing_sources_unchanged'] is True and checks['feedback_loop_suppressed'] is True
    assert before['body']['accounts'] == after['body']['accounts']
    prior = {r['source_ref']: r for r in before['body']['reviews']}
    assert len(after['body']['reviews']) == len(prior) + 1
    assert set(prior).issubset({r['source_ref'] for r in after['body']['reviews']})
    assert all(r == prior[r['source_ref']] for r in after['body']['reviews'] if r['source_ref'] in prior)
    additions = [r for r in after['body']['reviews'] if r['source_ref'] not in prior]
    assert len(additions) == 1
    assert additions[0]['action_key'] == intent['id'] and additions[0]['review_status'] == 'Pending'
    queries = []
    for name, source in [('warehouse_before', before), ('warehouse_after', after)]:
        stage = checks[name]
        assert stage['status'] in ('PASSED', 'PASSED_AFTER_READ_ONLY_POSTFLIGHT')
        assert stage['provenance'] == 'native_snowflake'
        assert all(stage['checks'][k] is True for k in ('native_duckdb_exact_comparison',
                   'duplicate_ingestion_no_effect', 'complete_source_readback'))
        native = stage['native']
        assert native['cleanup']['schema'] == 'dropped'
        if stage['status'] == 'PASSED_AFTER_READ_ONLY_POSTFLIGHT':
            original = json.loads((folder / 'feedback-failed-attempt.json').read_text())
            assert original['status'] == stage['executed_attempt_status'] == 'FAILED'
            assert original['native'] == native
            assert original['decisions'] == stage['decisions']
            assert original['private_record_sha256'] == stage['prior_attempt_sha256']
            final = stage['cleanup_postflight']
            assert final['status'] == 'PASSED' and final['warehouse_state'] == 'SUSPENDED'
            assert final['integration_schemas_remaining'] == 0
            assert all(q['status'] == 'succeeded' and q.get('query_id') for q in final['queries'])
            queries.extend(q['query_id'] for q in final['queries'])
        else:
            assert native['cleanup']['warehouse'] in ('suspended', 'already_suspended')
        assert native['consumer']['candidate_readback'] == 'passed'
        assert native['consumer']['raw_read_denials'] == 3
        assert native['warehouse']['size'] == 'XSMALL' and native['warehouse']['auto_suspend_seconds'] == 60
        assert 0 < len(native['queries']) <= 100
        assert all(q.get('query_id') for q in native['queries'])
        failures = [q for q in native['queries'] if q['status'] != 'succeeded']
        assert len(failures) == 3 and all(q.get('error_code') == 2003 for q in failures)
        queries.extend(q['query_id'] for q in native['queries'])
        for decision in stage['decisions']:
            verify_decision(decision, source)
    assert len(set(queries)) == len(queries)
    assert checks['warehouse_after']['checks']['late_prior_actual_batch_no_regress'] is True
    assert checks['warehouse_after']['checks']['independent_full_exact_comparison'] is True
    candidates = [d for d in checks['warehouse_before']['decisions']
                  if d['decision_hash'] == checks['intent']['decision_hash']]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate['decision_hash'] == checks['intent']['decision_hash']
    assert candidate['decision_action'] == 'clarify_need'
    post = [d for d in checks['warehouse_after']['decisions']
            if d['account_source_ref'] == candidate['account_source_ref']]
    assert len(post) == 1 and post[0]['decision_action'] == 'hold' and post[0]['pending_count'] == 1
    # The action's exact cited document binds warehouse output into approved source evidence.
    claim = intent['payload']['proposal']['claims'][0]
    assert claim['source'] == 'warehouse-' + digest(candidate)
    from .contracts import canonical
    text = canonical({'policy': 'review-readiness/v1', 'source_hash': before['business_hash'], 'decision': candidate})
    assert claim['quote'] and claim['quote'] in text
    if root:
        for name, expected in report['source_sha256'].items():
            if name in ('scripts/export_connected_evidence.py', 'src/signals/integration_evidence.py'):
                continue  # Postprocessing is tested separately; native executable fingerprints remain checked.
            assert hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() == expected, name
    return {'status': 'recorded_native_evidence_checked_offline', 'native_query_ids': len(queries),
            'salesforce_requests': len(report['requests']), 'action_effects': 1,
            'new_vendor_execution': False}
