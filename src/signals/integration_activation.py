"""Warehouse evidence joins the existing workbench approval and Salesforce journal."""
import json
import sqlite3

from .contracts import canonical, digest
from .salesforce_contract import DeliveryError
from .salesforce_delivery import SalesforceInbox, OBJECT
from .store import Refused

POLICY = 'review-readiness/v1'


def verify_decision(decision, envelope):
    """Independent Python oracle reconciles every SQL decision field to source rows."""
    from .integration_warehouse import utc_timestamp
    if digest(envelope['body']) != envelope['business_hash']:
        raise Refused('source_envelope_tampered')
    accounts = envelope['body']['accounts']
    matches = [a for a in accounts if a['source_ref'] == decision.get('account_source_ref')]
    if len(matches) != 1:
        raise Refused('warehouse_identity_not_in_source')
    account = dict(matches[0], source_modified_at=utc_timestamp(matches[0]['source_modified_at']))
    reviews = sorted([dict(r, source_modified_at=utc_timestamp(r['source_modified_at']))
                      for r in envelope['body']['reviews'] if r['account_source_ref'] == account['source_ref']],
                     key=lambda r: r['source_ref'])
    if len({r['source_ref'] for r in reviews}) != len(reviews):
        raise Refused('warehouse_source_grain_violation')
    expected = {k: v for k, v in account.items() if k != 'source_ref'}
    expected['account_source_ref'] = account['source_ref']
    expected.update(review_count=len(reviews), pending_count=sum(r['review_status'] == 'Pending' for r in reviews),
                    reviewed_count=sum(r['review_status'] == 'Reviewed' for r in reviews),
                    rejected_count=sum(r['review_status'] == 'Rejected' for r in reviews))
    expected['decision_action'] = ('clarify_need' if account['active'] and account['synthetic']
                                   and expected['pending_count'] == 0 and expected['reviewed_count'] > 0 else 'hold')
    expected['source_hash'] = digest({'account': account, 'reviews': reviews})
    expected['decision_hash'] = digest(expected)
    if expected != decision:
        raise Refused('warehouse_result_does_not_reconcile')
    return expected['decision_action'] == 'clarify_need'


class WarehouseResponder:
    """Deterministic SQL evidence summary; no model inference or contact execution."""
    def __init__(self, decision, source_hash):
        self.decision, self.source_hash = decision, source_hash
        self.config = {'mode': 'deterministic_warehouse_policy', 'policy': POLICY,
                       'decision_hash': digest(decision), 'source_hash': source_hash}

    def generate(self, snapshot):
        doc = next(d for d in snapshot['documents'] if d['id'] == 'warehouse-' + digest(self.decision))
        return {'assessment': 'Review completed synthetic account history and clarify the next internal step.',
                'action': 'clarify_need', 'claims': [{'source': doc['id'], 'quote': doc['text'][:400]}],
                'draft': 'Internal synthetic review only. Previous reviews are complete and no review is pending. '
                         'Confirm the next requirement with the approved account owner; this does not authorize contact.',
                'questions': ['What internal follow-up, if any, should the account owner approve?'],
                'uncertainties': ['Review completion is not a sale, consent grant or customer outcome.']}, {
                    'mode': 'deterministic_warehouse_policy', 'usage': {'total_tokens': 0}}


def prepare(bench, decision, envelope, *, eligible, actor='approved-synthetic-integration-policy'):
    """Use normal document admission, proposal validation and immutable approval machinery."""
    if not eligible or not verify_decision(decision, envelope):
        raise Refused('warehouse_decision_not_eligible')
    source = next((r for r in envelope['body']['accounts'] if r['brand'] == decision['brand']
                   and r['account_key'] == decision['account_key']), None)
    if source is None:
        raise Refused('warehouse_identity_not_in_source')
    with bench.store.tx() as c:
        local = bench.snapshot(c, source['brand'], source['account_key'])
        if local['decision']['owner'] != source['owner_key']:
            raise Refused('warehouse_owner_conflicts_with_authority')
    # Provenance timestamps/query IDs live outside stable business identity.
    text = canonical({'policy': POLICY, 'source_hash': envelope['business_hash'], 'decision': decision})
    from datetime import datetime, timezone
    doc_id = 'warehouse-' + digest(decision)
    occurred = datetime.fromtimestamp(bench.clock(), timezone.utc).isoformat().replace('+00:00', 'Z')
    with bench.store.tx() as c:
        old_doc = c.execute('SELECT body FROM seller_documents WHERE id=?', (doc_id,)).fetchone()
        if old_doc:
            occurred = json.loads(old_doc[0])['occurred_at']
    bench.document({'id': doc_id, 'brand': source['brand'],
                    'account': source['account_key'], 'revision': 1, 'title': 'Warehouse review-readiness evidence',
                    'kind': 'account_document', 'occurred_at': occurred, 'text': text}, actor)
    bench.model = WarehouseResponder(decision, envelope['business_hash'])
    with bench.store.tx() as c:
        current = bench.snapshot(c, source['brand'], source['account_key'])
        prior = [json.loads(r[0]) for r in c.execute('SELECT body FROM seller_runs')]
        run = next((r for r in prior if r['configuration'] == bench.model.config
                    and r['snapshot']['state_hash'] == current['state_hash'] and r['status'] == 'review_required'), None)
    if run is None:
        generated = bench.generate(source['brand'], source['account_key'], actor)
        with bench.store.tx() as c:
            run = bench.get_run(c, generated['id'])
    if run['status'] != 'review_required':
        raise Refused('warehouse_proposal_invalid')
    return bench.approve(run['id'], run['proposal'], digest(run), actor)


class GuardedSalesforceInbox(SalesforceInbox):
    """Same adapter and journal, with a persistent last-dispatch uncertainty boundary.

    A 404 after an uncertain POST cannot authorize another POST. An exact receipt can
    still reconcile through the existing dispatcher, even after authority changes.
    """
    def __init__(self, client, approval, mapping, *, journal, authorize):
        super().__init__(client, approval, mapping)
        self.journal_path, self.authorize = journal, authorize
        with sqlite3.connect(journal) as c:
            c.execute('CREATE TABLE IF NOT EXISTS integration_dispatch '
                      '(action_key TEXT PRIMARY KEY, outcome TEXT NOT NULL, attempts INTEGER NOT NULL)')

    def _request(self, method, path, **kwargs):
        if method != 'POST':
            return super()._request(method, path, **kwargs)
        if path != f'/sobjects/{OBJECT}/':
            raise DeliveryError('destination_not_allowlisted')
        key = kwargs['json']['Action_Key__c']
        # This executes at the actual write boundary, after receipt lookup and mapping validation.
        self.authorize()
        with sqlite3.connect(self.journal_path, timeout=30) as c:
            c.execute('BEGIN IMMEDIATE')
            prior = c.execute('SELECT outcome,attempts FROM integration_dispatch WHERE action_key=?', (key,)).fetchone()
            if prior and prior[0] != 'rejected':
                raise DeliveryError('uncertain_remote_effect_read_only_required')
            c.execute('INSERT INTO integration_dispatch VALUES(?,?,?) ON CONFLICT(action_key) '
                      'DO UPDATE SET outcome=excluded.outcome,attempts=excluded.attempts',
                      (key, 'unknown', 1 if not prior else prior[1] + 1))
        response = super()._request(method, path, **kwargs)
        # Only definite API rejection permits retry. 5xx/network/process death remain unknown.
        outcome = 'committed' if response.status_code == 201 else 'unknown'
        if response.status_code in (400, 401, 403, 429):
            outcome = 'rejected'
        with sqlite3.connect(self.journal_path) as c:
            c.execute('UPDATE integration_dispatch SET outcome=? WHERE action_key=?', (outcome, key))
        return response


def verify_receipt(inbox, key, payload, *, independent_client):
    """Independent identity reads the effect; exact business fields, not just HTTP 201."""
    from .salesforce_delivery import API, _body
    expected = _body(payload, inbox.mapping)
    response = independent_client.request('GET', API + f'/sobjects/{OBJECT}/Action_Key__c/{key}')
    inbox._require_success(response)
    record = inbox._json(response)
    if not isinstance(record, dict) or any(record.get(k) != v for k, v in expected.items()):
        raise DeliveryError('independent_reconciliation_mismatch')
    if digest(json.loads(record['Payload__c'])) != key:
        raise DeliveryError('independent_payload_mismatch')
    return {'action_key': key, 'payload_hash': key, 'exact_fields': len(expected),
            'record_ref': digest(record['Id']), 'independent_readback': True}
