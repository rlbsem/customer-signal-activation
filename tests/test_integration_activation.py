"""Connected contract/fault evidence uses DuckDB and local HTTP, never native vendors."""
import json
import sqlite3
import subprocess
import sys
import textwrap

import httpx
import pytest

from signals.contracts import digest
from signals.fixtures import AS_OF
from signals.integration_activation import GuardedSalesforceInbox, prepare, verify_receipt
from signals.integration_warehouse import LocalWarehouse
from signals.salesforce_contract import DeliveryError
from signals.seller import Workbench
from signals.seller_fixtures import seed_workbench
from signals.store import Refused, Store
from test_salesforce_delivery import count, payload as payload_fixture, remote as remote_fixture
from test_salesforce_acceptance import make_worker, revoke
from test_integration_source import source_fixture as local_source_fixture

remote = remote_fixture
payload = payload_fixture
source_fixture = local_source_fixture


def guarded(remote, tmp_path, authorize=lambda: None):
    original, _ = remote
    inbox = GuardedSalesforceInbox(original.client, original.approval, original.mapping,
        journal=tmp_path / 'uncertain.sqlite', authorize=authorize)
    inbox.preflight()
    return inbox


def decision_for(source):
    envelope = source.extract()
    with LocalWarehouse() as warehouse:
        warehouse.load(**envelope['body'], run_id='contract-run')
        decision = warehouse.decisions()[0]
    assert decision['decision_action'] == 'clarify_need'
    return decision, envelope


@pytest.mark.parametrize('advance_seconds', [0, 30])
def test_real_sql_repeated_preparation_has_one_stable_approved_action(source_fixture, tmp_path, advance_seconds):
    source, _ = source_fixture
    decision, envelope = decision_for(source)
    bench = Workbench(Store(tmp_path / 'bench.sqlite'), as_of=AS_OF)
    seed_workbench(bench)
    first = prepare(bench, decision, envelope, eligible=True)
    bench.as_of += advance_seconds
    # Observation time changes are operational metadata, not a new business intent.
    envelope['observed_at'] += advance_seconds
    second = prepare(bench, decision, envelope, eligible=True)
    assert first['id'] == second['id']
    assert first['payload'] == second['payload']
    with bench.store.tx() as c:
        assert c.execute('SELECT COUNT(*) FROM seller_actions').fetchone()[0] == 1


def test_warehouse_evidence_never_overrides_current_privacy_authority(source_fixture, tmp_path):
    source, _ = source_fixture
    decision, envelope = decision_for(source)
    bench = Workbench(Store(tmp_path / 'bench.sqlite'), as_of=AS_OF)
    seed_workbench(bench)
    revoke(bench)
    with pytest.raises(Refused, match='policy_blocks'):
        prepare(bench, decision, envelope, eligible=True)
    with bench.store.tx() as c:
        assert c.execute('SELECT COUNT(*) FROM seller_actions').fetchone()[0] == 0


@pytest.mark.parametrize('field,value', [('reviewed_count', 300), ('pending_count', 5),
    ('owner_key', 'cedar-west'), ('decision_action', 'schedule_discovery')])
def test_recomputed_hash_does_not_hide_forged_sql_result(source_fixture, tmp_path, field, value):
    source, _ = source_fixture
    decision, envelope = decision_for(source)
    decision[field] = value
    decision['decision_hash'] = digest({k: v for k, v in decision.items() if k != 'decision_hash'})
    bench = Workbench(Store(tmp_path / 'bench.sqlite'), as_of=AS_OF)
    seed_workbench(bench)
    with pytest.raises(Refused, match='warehouse_result_does_not_reconcile'):
        prepare(bench, decision, envelope, eligible=True)
    with bench.store.tx() as c:
        assert c.execute('SELECT COUNT(*) FROM seller_actions').fetchone()[0] == 0


def test_current_crm_change_blocks_before_post(remote, source_fixture, tmp_path, payload):
    source, state = source_fixture
    approved = source.extract()
    inbox = guarded(remote, tmp_path, authorize=lambda: source.assert_current(approved))
    state['reviews'][0]['Review_Status__c'] = 'Pending'
    with pytest.raises(DeliveryError, match='crm_changed'):
        inbox.create(digest(payload), payload)
    assert count(remote[1]) == 0
    assert not any(m == 'POST' for m, _ in remote[1]['requests'])


@pytest.mark.parametrize('fault', ['timeout', 'server_error', 'simulated_interruption'])
def test_uncertain_write_survives_fresh_adapter_and_absence_never_replays(remote, tmp_path, payload, monkeypatch, fault):
    inbox = guarded(remote, tmp_path)
    original = inbox.client.request
    posts = []

    def ambiguous(method, path, **kwargs):
        if method == 'POST':
            posts.append(path)
            if fault == 'simulated_interruption':
                raise KeyboardInterrupt('controlled interruption after durable intent')
            if fault == 'timeout':
                raise httpx.ReadTimeout('controlled unknown outcome')
            return httpx.Response(503, json=[{'errorCode': 'UNKNOWN'}])
        return original(method, path, **kwargs)

    monkeypatch.setattr(inbox.client, 'request', ambiguous)
    with pytest.raises(KeyboardInterrupt if fault == 'simulated_interruption' else DeliveryError):
        inbox.create(digest(payload), payload)
    assert count(remote[1]) == 0
    recovered = guarded(remote, tmp_path)
    with pytest.raises(DeliveryError, match='uncertain_remote_effect_read_only'):
        recovered.create(digest(payload), payload)
    assert len(posts) == 1 and count(remote[1]) == 0
    with sqlite3.connect(tmp_path / 'uncertain.sqlite') as c:
        assert c.execute('SELECT outcome,attempts FROM integration_dispatch').fetchone() == ('unknown', 1)


def test_actual_child_process_death_after_commit_reconciles_without_second_post(remote, tmp_path, payload):
    from test_salesforce_delivery import APPROVAL, ENTRY
    inbox = guarded(remote, tmp_path)
    child = tmp_path / 'crash_after_commit.py'
    child.write_text(textwrap.dedent('''
        import json
        import os
        import sys
        import httpx
        from signals.contracts import digest
        from signals.integration_activation import GuardedSalesforceInbox
        from signals.salesforce_contract import MappingBook, OrganizationApproval

        config = json.loads(sys.argv[1])
        class AbruptExitClient:
            def __init__(self, client):
                self.client = client
            def request(self, method, path, **kwargs):
                response = self.client.request(method, path, **kwargs)
                if method == 'POST' and response.status_code == 201:
                    os._exit(73)
                return response

        with httpx.Client(base_url=config['url'], trust_env=False,
            headers={'Authorization': 'Bearer test-only-token'}) as client:
            inbox = GuardedSalesforceInbox(AbruptExitClient(client),
                OrganizationApproval(**config['approval']), MappingBook([config['entry']]),
                journal=config['journal'], authorize=lambda: None)
            inbox.preflight()
            inbox.create(digest(config['payload']), config['payload'])
        raise SystemExit('fault point did not execute')
    '''), encoding='utf-8')
    config = {'url': str(inbox.client.base_url), 'approval': vars(APPROVAL), 'entry': ENTRY,
              'journal': str(tmp_path / 'uncertain.sqlite'), 'payload': payload}
    result = subprocess.run([sys.executable, str(child), json.dumps(config)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 73, result.stderr
    assert count(remote[1]) == 1
    with sqlite3.connect(tmp_path / 'uncertain.sqlite') as c:
        assert c.execute('SELECT outcome,attempts FROM integration_dispatch').fetchone() == ('unknown', 1)
    recovered = guarded(remote, tmp_path)
    assert recovered.create(digest(payload), payload)['payload_hash'] == digest(payload)
    assert count(remote[1]) == 1
    assert sum(method == 'POST' for method, _ in remote[1]['requests']) == 1


def test_committed_lost_ack_reconciles_after_privacy_and_crm_revocation(remote, tmp_path):
    permission = [True]

    def authorize():
        if not permission[0]:
            raise DeliveryError('current_source_revoked')

    inbox = guarded(remote, tmp_path, authorize)
    bench, action, worker = make_worker(tmp_path, inbox)
    remote[1]['fault'] = 'after_commit'
    assert worker.step(action['id'])['state'] == 'retry'
    assert count(remote[1]) == 1
    permission[0] = False
    revoke(bench)
    remote[1]['account']['Active__c'] = False
    fresh = guarded(remote, tmp_path, authorize)
    worker.inbox = fresh
    result = worker.reconcile_once(action['id'])
    assert result['state'] == 'delivered'
    assert json.loads(result['receipt'])['payload_hash'] == action['id']
    assert count(remote[1]) == 1
    assert sum(method == 'POST' for method, _ in remote[1]['requests']) == 1


@pytest.mark.parametrize('always_limited', [False, True])
def test_definite_rate_rejection_can_retry_with_bounded_exhaustion(remote, tmp_path, monkeypatch, always_limited):
    inbox = guarded(remote, tmp_path)
    original = inbox.client.request
    post_count = [0]

    def limited(method, path, **kwargs):
        if method == 'POST':
            post_count[0] += 1
            if always_limited or post_count[0] == 1:
                return httpx.Response(429, json=[{'errorCode': 'REQUEST_LIMIT_EXCEEDED'}],
                                      headers={'Retry-After': '3'})
        return original(method, path, **kwargs)

    monkeypatch.setattr(inbox.client, 'request', limited)
    clock = [100.0]
    _, action, worker = make_worker(tmp_path, inbox, attempts=2, clock=lambda: clock[0])
    first = worker.step(action['id'])
    assert first['state'] == 'retry' and count(remote[1]) == 0
    assert worker.step(action['id'])['state'] == 'retry' and post_count[0] == 1
    clock[0] = first['next_at']
    final = worker.step(action['id'])
    assert final['state'] == ('exhausted' if always_limited else 'delivered')
    assert post_count[0] == 2 and count(remote[1]) == (0 if always_limited else 1)
    worker.step(action['id'])
    assert post_count[0] == 2


@pytest.mark.parametrize('tamper', [None, 'Payload__c', 'Draft__c', 'Proposed_User__c', 'Action_Key__c'])
def test_independent_reconciliation_reads_exact_business_content(remote, tmp_path, payload, tamper):
    inbox = guarded(remote, tmp_path)
    key = digest(payload)
    inbox.create(key, payload)
    if tamper:
        with sqlite3.connect(remote[1]['path']) as c:
            raw = json.loads(c.execute('SELECT body FROM records WHERE key=?', (key,)).fetchone()[0])
            raw[tamper] = 'changed'
            c.execute('UPDATE records SET body=? WHERE key=?', (json.dumps(raw), key))
    with httpx.Client(base_url=str(inbox.client.base_url), trust_env=False,
                      headers={'Authorization': 'Bearer reviewer-test-token'}) as reader:
        if tamper:
            with pytest.raises(DeliveryError, match='independent_reconciliation_mismatch'):
                verify_receipt(inbox, key, payload, independent_client=reader)
        else:
            checked = verify_receipt(inbox, key, payload, independent_client=reader)
            assert checked['independent_readback'] and checked['payload_hash'] == key
