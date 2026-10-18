"""Native Salesforce -> Snowflake -> reviewed Salesforce destination, bounded and resumable.

All runtime files are private. Export only through export_connected_evidence.py.
The existing administrator is read-only; only the integration identity can create.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from run_salesforce_acceptance import access_token
from signals.contracts import canonical, digest
from signals.fixtures import AS_OF
from signals.integration_activation import GuardedSalesforceInbox, prepare, verify_decision, verify_receipt
from signals.integration_source import SalesforceSource
from signals.salesforce_acceptance import ObservedClient, preflight, identity
from signals.salesforce_contract import DeliveryError, MappingBook, OrganizationApproval
from signals.salesforce_delivery import native_client, API, OBJECT
from signals.salesforce_dispatch import SalesforceDispatcher
from signals.seller import Workbench
from signals.seller_fixtures import seed_workbench
from signals.store import Store

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def fingerprint():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('src', 'scripts') for p in (ROOT / folder).rglob('*')
            if p.is_file() and p.suffix in ('.py', '.sql')}


def warehouse(args, source, output, *, checkpoint=None):
    script = 'postflight_connected_warehouse.py' if checkpoint else 'run_connected_warehouse.py'
    command = [args.warehouse_python, str(ROOT / 'scripts' / script),
               '--config', args.snowflake_config, '--input', str(source), '--output', str(output)]
    if checkpoint:
        command.extend(['--attempt', str(checkpoint)])
    elif args.owner_confirmed_fixture_monitor:
        command.append('--owner-confirmed-fixture-monitor')
    result = subprocess.run(command, capture_output=True, text=True, timeout=240)
    if not output.exists():
        output.with_suffix('.private-diagnostic.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        raise DeliveryError('warehouse_process_failed_no_evidence')
    record = json.loads(output.read_text())
    if result.returncode or record.get('status') not in ('PASSED', 'PASSED_AFTER_READ_ONLY_POSTFLIGHT'):
        raise DeliveryError('warehouse_execution_blocked_' + record.get('error_type', 'unknown'))
    return record


def finish(args, work, record, source, inbox, reviewer, intent, envelope):
    """Only CRM reads; continue a committed intent without recreating or reapproving it."""
    record['checks']['independent_readback'] = verify_receipt(
        inbox, intent['id'], intent['payload'], independent_client=reviewer)
    # The independent reviewer has explicit custom-field read access. Administrator
    # ViewAllData alone does not establish custom-field FLS (the failed attempt is retained).
    count = reviewer.request('GET', API + '/query', params={
        'q': f"SELECT COUNT(Id) n FROM {OBJECT} WHERE Action_Key__c='{intent['id']}'"})
    inbox._require_success(count)
    try:
        data = inbox._json(count)
    except ValueError:
        raise DeliveryError('independent_cardinality_mismatch') from None
    if (not isinstance(data, dict) or data.get('done') is not True or not isinstance(data.get('records'), list)
            or len(data['records']) != 1 or not isinstance(data['records'][0], dict)
            or type(data['records'][0].get('n')) is not int or data['records'][0]['n'] != 1):
        raise DeliveryError('independent_cardinality_mismatch')
    record['checks']['independent_action_count'] = 1
    after = source.extract()
    save(work / 'source-after.json', after)
    if len(after['body']['reviews']) != len(envelope['body']['reviews']) + 1:
        raise DeliveryError('unexpected_review_set_change')
    prior = {r['source_ref']: r for r in envelope['body']['reviews']}
    current_refs = {r['source_ref'] for r in after['body']['reviews']}
    additions = [r for r in after['body']['reviews'] if r['source_ref'] not in prior]
    if (after['body']['accounts'] != envelope['body']['accounts'] or not set(prior).issubset(current_refs)
            or len(additions) != 1 or additions[0]['action_key'] != intent['id']
            or any(r != prior[r['source_ref']] for r in after['body']['reviews'] if r['source_ref'] in prior)):
        raise DeliveryError('authoritative_state_regressed')
    record['checks']['existing_sources_unchanged'] = True
    save(work / 'roundtrip-input.json', {'before': envelope, 'after': after})
    closed = warehouse(args, work / 'roundtrip-input.json', work / 'warehouse-after.json',
                       checkpoint=getattr(args, 'feedback_checkpoint', None))
    if getattr(args, 'feedback_checkpoint', None):
        save(work / 'warehouse-feedback-failed-attempt.json', json.loads(Path(args.feedback_checkpoint).read_text()))
    for decision in closed['decisions']:
        verify_decision(decision, after)
    target = next(d for d in closed['decisions'] if (d['brand'], d['account_key'])
                  == (intent['payload']['brand'], intent['payload']['account']))
    if target['pending_count'] != 1 or target['decision_action'] != 'hold':
        raise DeliveryError('feedback_loop_not_suppressed')
    record['checks']['warehouse_after'] = closed
    record['checks']['feedback_loop_suppressed'] = True
    record['status'] = 'PASSED'


def resume_inputs(previous, current_fingerprints):
    """A matching durable approval and completed prewrite checkpoints are required."""
    prior = json.loads((previous / 'verification.json').read_text())
    intent = json.loads((previous / 'intent.json').read_text())
    envelope = json.loads((previous / 'source.json').read_text())
    if (prior['provenance'] != 'native_connected_salesforce_snowflake'
            or digest(intent['payload']) != intent['id']
            or digest(envelope['body']) != envelope['business_hash']
            or prior['checks']['intent']['action_key'] != intent['id']
            or prior['checks']['intent']['source_hash'] != envelope['business_hash']
            or prior['checks']['recovery']['restarted_state'] != 'delivered'):
        raise DeliveryError('incompatible_continuation_checkpoint')
    required = {'src/signals/' + name + '.py' for name in ('integration_activation', 'integration_source',
                'integration_warehouse', 'integration_snowflake', 'salesforce_contract', 'salesforce_delivery',
                'salesforce_dispatch', 'seller', 'store')}
    if not required.issubset(prior['source_sha256']):
        raise DeliveryError('continuation_fingerprint_inventory_incomplete')
    for name, value in prior['source_sha256'].items():
        if name.startswith('src/signals/') and 'integration_evidence' not in name:
            if current_fingerprints.get(name) != value:
                raise DeliveryError('continuation_business_code_changed')
    return prior, intent, envelope


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--salesforce-config', required=True)
    parser.add_argument('--snowflake-config')
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--sf-executable', default='sf')
    parser.add_argument('--warehouse-python', default=sys.executable)
    parser.add_argument('--mode', choices=('extract', 'acceptance', 'reconcile', 'finish'), default='extract')
    parser.add_argument('--resume-from')
    parser.add_argument('--feedback-checkpoint', help='Preserved completed feedback attempt needing metadata-only cleanup confirmation')
    parser.add_argument('--execute-approved-synthetic-writes', action='store_true')
    parser.add_argument('--owner-confirmed-fixture-monitor', action='store_true')
    args = parser.parse_args(argv)
    if args.mode == 'acceptance' and (not args.execute_approved_synthetic_writes or not args.snowflake_config):
        parser.error('acceptance requires existing Snowflake configuration and explicit synthetic-write approval')
    if args.mode in ('finish', 'reconcile') and not args.resume_from:
        parser.error('read-only continuation requires --resume-from with its prior durable state')
    if args.mode == 'finish' and not args.snowflake_config:
        parser.error('finish requires existing Snowflake configuration')
    work = Path(args.workspace).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if ROOT == work or ROOT not in work.parents or not any(p in ('.local', 'work') for p in work.relative_to(ROOT).parts):
        parser.error('workspace must be under repository .local/ or work/ (never public evidence)')
    if (work / 'verification.json').exists():
        parser.error('use a fresh report workspace and --resume-from; previous records remain immutable')
    record = {'status': 'FAILED', 'provenance': 'native_connected_salesforce_snowflake',
              'started_utc': datetime.now(timezone.utc).isoformat(), 'checks': {}, 'source_sha256': fingerprint(),
              'inference': 'not_executed_deterministic_policy', 'scope': 'synthetic_internal_review_only'}
    clients = []
    inherited_requests = []
    try:
        config = json.loads(Path(args.salesforce_config).read_text(encoding='utf-8'))
        approval, mappings = OrganizationApproval(**config['approval']), MappingBook(config['mappings'])
        with ExitStack() as stack:
            for alias, read_only in [('csa-demo-integration', args.mode != 'acceptance'),
                                      ('csa-demo-reviewer', True), ('csa-demo-owner', True)]:
                token = access_token(args.sf_executable, alias)
                clients.append(ObservedClient(stack.enter_context(native_client(config['instance_url'], token)),
                                              read_only=read_only))
            state = Path(args.resume_from).resolve() if args.resume_from else work
            journal = state / 'journal.sqlite'
            authorized = {}

            def authorize():
                identity(clients[0], approval, config['integration_user_id'])
                inbox.preflight(inbox.environment_attestation)
                source.assert_current(authorized['envelope'])

            inbox = GuardedSalesforceInbox(clients[0], approval, mappings, journal=journal, authorize=authorize)
            record['checks']['preflight'] = preflight(inbox, clients[1], config['integration_user_id'],
                                                       config['reviewer_user_id'], admin=clients[2])
            source = SalesforceSource(inbox, config['mappings'])
            if args.resume_from and (not journal.is_file() or not (state / 'workbench.sqlite').is_file()):
                raise DeliveryError('durable_state_missing')
            bench = Workbench(Store(state / 'workbench.sqlite'), None, AS_OF)
            if not args.resume_from:
                seed_workbench(bench)
            dispatcher = SalesforceDispatcher(bench, inbox, journal)
            if args.mode in ('reconcile', 'finish'):
                prior, intent, envelope = resume_inputs(state, record['source_sha256'])
                save(work / 'source.json', envelope)
                save(work / 'intent.json', intent)
                save(work / 'prior-verification.json', prior)
                current_preflight = record['checks']['preflight']
                record['checks'] = dict(prior['checks'], continuation_preflight=current_preflight)
                record['continuation'] = {'prior_private_record_sha256': hashlib.sha256(
                    (state / 'verification.json').read_bytes()).hexdigest(), 'prior_status': prior['status'],
                    'prior_error': prior.get('error'), 'prior_source_sha256': prior['source_sha256'],
                    'native_business_code_matches': True, 'new_salesforce_writes_permitted': False}
                inherited_requests = [dict(r, stage='initial_attempt') for r in prior['requests']]
                record['checks']['reconcile'] = dispatcher.reconcile_once(intent['id'])['state']
                if record['checks']['reconcile'] != 'delivered':
                    raise DeliveryError('prior_effect_not_reconciled')
                record['checks']['independent_readback'] = verify_receipt(
                    inbox, intent['id'], intent['payload'], independent_client=clients[1])
                record['status'] = 'PASSED_READ_ONLY_RECONCILIATION'
                if args.mode == 'finish':
                    finish(args, work, record, source, inbox, clients[1], intent, envelope)
            else:
                envelope = source.extract()
                save(work / 'source.json', envelope)
                record['checks']['source'] = {'accounts': len(envelope['body']['accounts']),
                                              'reviews': len(envelope['body']['reviews']),
                                              'business_hash': envelope['business_hash']}
                if args.mode == 'extract':
                    record['status'] = 'PASSED_READ_ONLY_EXTRACTION'
                else:
                    result = warehouse(args, work / 'source.json', work / 'warehouse-before.json')
                    record['checks']['warehouse_before'] = result
                    decisions = result['decisions']
                    eligible = [d for d in decisions if verify_decision(d, envelope)]
                    if len(eligible) != 1:
                        raise DeliveryError('exactly_one_eligible_synthetic_account_required')
                    authorized['envelope'] = envelope
                    source.assert_current(envelope)
                    intent = prepare(bench, eligible[0], envelope, eligible=True)
                    save(work / 'intent.json', intent)
                    record['checks']['intent'] = {'action_key': intent['id'], 'decision_hash': eligible[0]['decision_hash'],
                                                  'source_hash': envelope['business_hash'],
                                                  'approval': 'owner_authorized_synthetic_policy_not_human_business_review'}
                    # Drop an actual successful response, retaining server effect and durable intent.
                    clients[0].drop_next_create = True
                    first = dispatcher.step(intent['id'])
                    record['checks']['lost_ack_first_state'] = first['state']
                    if first['state'] != 'retry':
                        raise DeliveryError('lost_ack_experiment_not_established')
                    time.sleep(max(0, first['next_at'] - time.time()) + 0.05)
                    # Reopen persisted databases; process-death fault is a distinct local experiment.
                    restarted = SalesforceDispatcher(Workbench(Store(work / 'workbench.sqlite'), None, AS_OF), inbox, journal)
                    recovered = restarted.step(intent['id'])
                    if recovered['state'] != 'delivered':
                        raise DeliveryError('lost_ack_recovery_incomplete')
                    posts = sum(c['method'] == 'POST' for c in clients[0].calls)
                    repeated = restarted.step(intent['id'])
                    if repeated['state'] != 'delivered' or posts != 1 or sum(c['method'] == 'POST' for c in clients[0].calls) != 1:
                        raise DeliveryError('duplicate_effect_or_replay')
                    record['checks']['recovery'] = {'first_state': first['state'], 'restarted_state': recovered['state'],
                                                    'repeated_state': repeated['state'], 'post_requests': posts}
                    record['checks']['independent_readback'] = verify_receipt(
                        inbox, intent['id'], intent['payload'], independent_client=clients[1])
                    finish(args, work, record, source, inbox, clients[1], intent, envelope)
    except Exception as exc:
        record.update(status='FAILED', error_type=type(exc).__name__,
                      error=str(exc) if isinstance(exc, DeliveryError) else 'private_diagnostic_required')
    finally:
        record['requests'] = inherited_requests + [dict(e, actor=('integration', 'reviewer', 'administrator')[i],
                                                       stage='continuation' if args.resume_from else 'initial_attempt')
                              for i, client in enumerate(clients) for e in client.calls]
        record['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save(work / 'verification.json', record)
    print(canonical({'status': record['status'], 'error': record.get('error'), 'requests': len(record['requests'])}))
    return 0 if record['status'].startswith('PASSED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
