"""Local HTTP contract tests; these do not establish native Salesforce execution."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import httpx
import pytest

from signals.contracts import digest
from signals.integration_source import SalesforceSource
from signals.salesforce_contract import DeliveryError
from signals.salesforce_delivery import FIELDS, LOOKUPS, OBJECT, SalesforceInbox
from test_salesforce_delivery import APPROVAL, ENTRY, mapping

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def source_fixture():
    state = {'account': {'Id': ENTRY['registry_id'], 'SystemModstamp': '2026-10-17T11:00:00.000Z',
        'Account_Key__c': 'cedar:account-0012', 'Brand__c': 'cedar',
        'Approved_Owner__c': ENTRY['user_id'], 'Active__c': True, 'Synthetic__c': True},
        'reviews': [{'Id': 'a02000000000001AAA', 'SystemModstamp': '2026-10-17T11:00:00.000Z',
        'Synthetic_Account__c': ENTRY['registry_id'], 'Brand__c': 'cedar', 'Account_Key__c': 'account-0012',
        'Proposed_User__c': ENTRY['user_id'], 'Action_Key__c': 'a' * 64,
        'Review_Status__c': 'Reviewed', 'Proposed_Action__c': 'clarify_need'}], 'clock': NOW, 'queries': []}

    def respond(request):
        assert request.method == 'GET'
        if request.url.path.endswith('/describe'):
            return httpx.Response(200, json={'name': OBJECT, 'createable': True, 'queryable': True,
                'updateable': False, 'deletable': False,
                'fields': [{'name': k, 'length': n, 'createable': True,
                    'type': 'textarea' if k in ('Payload__c', 'Draft__c') else 'string',
                    'unique': k == 'Action_Key__c', 'externalId': k == 'Action_Key__c'} for k, n in FIELDS.items()]
                + [{'name': k, 'createable': True, 'type': 'reference', 'referenceTo': [v]} for k, v in LOOKUPS.items()]})
        query = request.url.params['q']
        if 'FROM Organization' in query:
            rows = [{'Id': APPROVAL.org_id, 'OrganizationType': APPROVAL.organization_type, 'IsSandbox': True}]
            return httpx.Response(200, json={'done': True, 'totalSize': 1, 'records': rows})
        state['queries'].append(query)
        rows = [state['account']] if 'FROM Synthetic_Account__c' in query else state['reviews']
        result = {'done': True, 'totalSize': len(rows), 'records': deepcopy(rows)}
        if state.get('override'):
            result.update(state['override'])
        return httpx.Response(200, json=result)

    with httpx.Client(base_url='https://local-contract.invalid', transport=httpx.MockTransport(respond)) as client:
        inbox = SalesforceInbox(client, APPROVAL, mapping())
        inbox.preflight()
        yield SalesforceSource(inbox, [ENTRY], clock=lambda: state['clock']), state


def test_source_projection_identity_hash_and_readonly_queries(source_fixture):
    source, state = source_fixture
    first = source.extract()
    state['clock'] += 30
    second = source.extract()
    assert first['business_hash'] == second['business_hash'] == digest(first['body'])
    assert first['observed_at'] != second['observed_at']
    assert len(first['body']['accounts']) == len(first['body']['reviews']) == 1
    assert ENTRY['registry_id'] not in json.dumps(first) and ENTRY['user_id'] not in json.dumps(first)
    assert all('LIMIT 101' in q and ENTRY['registry_id'] in q for q in state['queries'])
    assert all('Payload__c' not in q and 'Reviewer_Notes__c' not in q for q in state['queries'])


@pytest.mark.parametrize('override', [
    {'done': False}, {'totalSize': 2}, {'totalSize': True}, {'records': None},
    {'records': [None], 'totalSize': 1}, {'records': [{}], 'totalSize': 1},
    {'records': [{}] * 101, 'totalSize': 101}])
def test_incomplete_malformed_or_oversize_extraction_fails_closed(source_fixture, override):
    source, state = source_fixture
    state['override'] = override
    with pytest.raises(DeliveryError):
        source.extract()


@pytest.mark.parametrize('field,value', [('Id', 'a01000000000002AAA'), ('Brand__c', 'harbour'),
    ('Approved_Owner__c', '005000000000002AAA'), ('Account_Key__c', 'cedar:account-9999'),
    ('Active__c', 1), ('Synthetic__c', 'true'), ('SystemModstamp', '2026-10-17T13:00:00Z'),
    ('SystemModstamp', '2026-10-17T11:00:00'), ('SystemModstamp', 'invalid')])
def test_account_identity_type_and_future_version_rejected(source_fixture, field, value):
    source, state = source_fixture
    state['account'][field] = value
    with pytest.raises(DeliveryError):
        source.extract()


@pytest.mark.parametrize('field,value', [('Synthetic_Account__c', 'a01000000000002AAA'),
    ('Proposed_User__c', '005000000000002AAA'), ('Action_Key__c', 'invalid'),
    ('Review_Status__c', 'Approved'), ('Proposed_Action__c', 'send_email')])
def test_review_relationship_and_action_contract_rejected(source_fixture, field, value):
    source, state = source_fixture
    state['reviews'][0][field] = value
    with pytest.raises(DeliveryError):
        source.extract()


def test_extra_fields_do_not_silently_enter_source_lineage(source_fixture):
    source, state = source_fixture
    state['account']['Customer_Secret__c'] = 'must-not-enter-the-pipeline'
    with pytest.raises(DeliveryError, match='projection_drift'):
        source.extract()


@pytest.mark.parametrize('change', ['account', 'review', 'expired', 'future_observation', 'tampered'])
def test_prewrite_revalidation_rejects_changed_or_untrusted_snapshot(source_fixture, change):
    source, state = source_fixture
    approved = source.extract()
    if change == 'account':
        state['account']['Active__c'] = False
    elif change == 'review':
        state['reviews'][0]['Review_Status__c'] = 'Pending'
    elif change == 'expired':
        state['clock'] += 301
    elif change == 'future_observation':
        approved['observed_at'] += 1
    else:
        approved['body']['accounts'][0]['active'] = False
    with pytest.raises(DeliveryError):
        source.assert_current(approved)


def test_extraction_requires_verified_environment_and_pinned_destination(source_fixture):
    source, state = source_fixture
    source.inbox.ready = False
    with pytest.raises(DeliveryError, match='preflight'):
        source.extract()
    assert not state['queries']


def test_duplicate_mapping_cannot_double_the_source_grain(source_fixture):
    source, _ = source_fixture
    with pytest.raises(DeliveryError):
        SalesforceSource(source.inbox, [ENTRY, ENTRY])
