"""Bounded, pinned Salesforce review-state extraction. No standard CRM objects or free text."""
from datetime import datetime, timezone
import re

from .contracts import digest
from .salesforce_contract import DeliveryError, sf_id

VERSION = 'salesforce-review-state/v1'
ACCOUNT_FIELDS = ('Id', 'SystemModstamp', 'Account_Key__c', 'Brand__c',
                  'Approved_Owner__c', 'Active__c', 'Synthetic__c')
REVIEW_FIELDS = ('Id', 'SystemModstamp', 'Synthetic_Account__c', 'Brand__c', 'Account_Key__c',
                 'Proposed_User__c', 'Action_Key__c', 'Review_Status__c', 'Proposed_Action__c')


def utc(value):
    if not isinstance(value, str):
        raise DeliveryError('source_timestamp_required')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError
        return stamp.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    except ValueError:
        raise DeliveryError('source_timestamp_required') from None


class SalesforceSource:
    def __init__(self, inbox, entries, *, clock=lambda: datetime.now(timezone.utc).timestamp()):
        self.inbox, self.entries, self.clock = inbox, [dict(e) for e in entries], clock
        if not 1 <= len(self.entries) <= 10:
            raise DeliveryError('bounded_mapping_required')
        if len({e['registry_id'] for e in self.entries}) != len(self.entries):
            raise DeliveryError('duplicate_mapping')
        for entry in self.entries:
            if self.inbox.mapping.resolve(entry) != entry:
                raise DeliveryError('mapping_changed')

    def _query(self, fields, table, predicate):
        response = self.inbox._request('GET', '/query', params={
            'q': f"SELECT {','.join(fields)} FROM {table} WHERE {predicate} ORDER BY Id LIMIT 101"})
        self.inbox._require_success(response)
        data = self.inbox._json(response)
        if (not isinstance(data, dict) or data.get('done') is not True
                or type(data.get('totalSize')) is not int or not isinstance(data.get('records'), list)
                or data['totalSize'] != len(data['records']) or len(data['records']) > 100):
            raise DeliveryError('source_incomplete_or_budget_exceeded')
        if any(not isinstance(r, dict) for r in data['records']):
            raise DeliveryError('source_projection_drift')
        rows = [{k: v for k, v in r.items() if k != 'attributes'} for r in data['records']]
        if any(set(r) != set(fields) for r in rows):
            raise DeliveryError('source_projection_drift')
        return rows

    def extract(self):
        if not self.inbox.ready or self.inbox._preflight_destination_pin != self.inbox.destination_pin:
            raise DeliveryError('preflight_required')
        accounts, reviews = [], []
        for entry in self.entries:
            registry = sf_id(entry['registry_id'])
            rows = self._query(ACCOUNT_FIELDS, 'Synthetic_Account__c', f"Id='{registry}'")
            if len(rows) != 1:
                raise DeliveryError('pinned_account_not_visible')
            row = rows[0]
            if (row['Id'] != registry or row['Brand__c'] != entry['brand']
                    or row['Account_Key__c'] != entry['brand'] + ':' + entry['account']
                    or row['Approved_Owner__c'] != entry['user_id']
                    or type(row['Active__c']) is not bool or type(row['Synthetic__c']) is not bool):
                raise DeliveryError('source_identity_or_owner_conflict')
            account_ref = digest({'org': self.inbox.approval.org_id, 'record': registry})
            accounts.append({'source_ref': account_ref, 'source_modified_at': utc(row['SystemModstamp']),
                             'brand': entry['brand'], 'account_key': entry['account'], 'owner_key': entry['owner'],
                             'owner_ref': digest(entry['user_id']), 'active': row['Active__c'],
                             'synthetic': row['Synthetic__c']})
            for r in self._query(REVIEW_FIELDS, 'Seller_Action__c', f"Synthetic_Account__c='{registry}'"):
                sf_id(r['Id'])
                if (r['Synthetic_Account__c'] != registry or r['Brand__c'] != entry['brand']
                        or r['Account_Key__c'] != entry['account'] or r['Proposed_User__c'] != entry['user_id']
                        or not isinstance(r['Action_Key__c'], str)
                        or not re.fullmatch('[0-9a-f]{64}', r['Action_Key__c'])
                        or r['Review_Status__c'] not in ('Pending', 'Reviewed', 'Rejected')
                        or r['Proposed_Action__c'] not in ('schedule_discovery', 'clarify_need', 'support_handoff')):
                    raise DeliveryError('review_identity_or_schema_conflict')
                reviews.append({'source_ref': digest({'org': self.inbox.approval.org_id, 'record': r['Id']}),
                                'source_modified_at': utc(r['SystemModstamp']), 'account_source_ref': account_ref,
                                'action_key': r['Action_Key__c'], 'review_status': r['Review_Status__c'],
                                'proposed_action': r['Proposed_Action__c']})
        body = {'accounts': sorted(accounts, key=lambda x: x['source_ref']),
                'reviews': sorted(reviews, key=lambda x: x['source_ref'])}
        if any(len({r['source_ref'] for r in rows}) != len(rows) for rows in body.values()):
            raise DeliveryError('source_grain_violation')
        if any(datetime.fromisoformat(r['source_modified_at'].replace('Z', '+00:00')).timestamp()
               > self.clock() + 60 for rows in body.values() for r in rows):
            raise DeliveryError('future_source_version')
        return {'contract': VERSION, 'source_authority': 'salesforce_synthetic_registry_and_review_state',
                'organization_ref': digest(self.inbox.approval.org_id), 'body': body,
                'business_hash': digest(body), 'observed_at': self.clock()}

    def assert_current(self, approved, *, max_age=300):
        if approved.get('contract') != VERSION or not 0 <= self.clock() - approved['observed_at'] <= max_age:
            raise DeliveryError('warehouse_snapshot_expired')
        if digest(approved['body']) != approved['business_hash']:
            raise DeliveryError('source_envelope_tampered')
        current = self.extract()
        if current['business_hash'] != approved['business_hash']:
            raise DeliveryError('crm_changed_after_warehouse')
        return current
