# Salesforce-native acceptance candidate

This revision supports explicitly approved, pinned **sandboxes and Developer Edition organizations**. Metadata is deployed and native preflight has passed in the isolated Developer Edition org. The scoped native delivery/security matrix completed across a recorded attempt and guarded continuation; failed intermediate records are preserved. This is not a claim of a single uninterrupted run or native browser validation. Existing inference and financial evidence is preserved. [Current native status](evidence/salesforce-native/README.md).

The outcome is a source-linked, human-approved seller recommendation visible for internal review in Salesforce. The adapter creates `Seller_Action__c`, a synthetic review record. It sends no email, creates no standard Task and changes no real Account or Opportunity. A proposed user is a review suggestion, not assignment of commercial activity.

## Architecture and controls

```text
Existing Workbench -> exact human approval -> action/payload hash
  -> SalesforceDispatcher (durable journal, bounded attempts and deadline)
     -> historical receipt lookup
     -> if absent: current evidence/consent + approved synthetic account/user mapping
     -> POST Seller_Action__c -> exact content read-back
Salesforce reviewer -> list/detail view -> Reviewed or Rejected + internal notes
```

- [Environment and mapping contract](../src/signals/salesforce_contract.py): approval pins an 18-character org ID, environment, exact observed OrganizationType and `approved=true`. Sandbox mode requires `IsSandbox=true`; Developer Edition mode requires `IsSandbox=false` and `OrganizationType='Developer Edition'`. Wrong ID/edition, missing fields, trial labels, ordinary production editions and unapproved configurations fail closed. A URL containing “dev” is never environment evidence.
- [Adapter](../src/signals/salesforce_delivery.py): HTTPS My Domain, no redirects/proxies, ten-second request timeout, effective create/read-only object permissions, unique external key, field types/sizes and lookup targets. Delivery never PATCHes/upserts. Every immutable display, mapping and payload field is checked on read-back; a create acknowledgement alone is insufficient.
- Environment verification uses an authenticated administrator's in-process attestation when restricted identities cannot query Organization. Identity checks still pin each restricted user to the same org. Direct adapter preflight without that attestation must query and verify Organization itself. The administrator transport allows GET only and is never used to perform delivery writes.
- Synthetic registry: the local allowlist pins brand/account/local owner to one `Synthetic_Account__c` row and one User ID. Before a new create, the adapter reads the registry and active user. Metadata validation enforces matching brand/key/user and active synthetic mapping at insert, closing the pre-read/commit race inside Salesforce's transaction. The integration cannot change the registry. Standard Accounts are never linked or mutated.
- [Dispatcher](../src/signals/salesforce_dispatch.py): intent commits to a separate SQLite journal before remote IO. The Workbench transaction serializes local source changes and dispatch. Defaults are four attempts and a one-hour lifetime, with exponential delay, bounded deterministic jitter and Retry-After handling. The operator invokes each step; there is no background daemon or automatic cloud polling. States include ready/inflight/retry/delivered/blocked/exhausted. Exhaustion means unresolved. Destination, mapping and retry policy are pinned in the journal.
- Historical reconciliation precedes current evidence checks. Revoked consent, expiry or rejection prevents a new POST but does not erase a committed effect. An authenticated operator can issue read-only reconciliation after exhaustion. It cannot reset the budget or create a record. Receipt checks use the approved mapping snapshot, so deactivation does not make history unverifiable. Retain old config/journal versions when mappings change.
- Two-file durability: a crash after journal acknowledgement but before the Workbench commit recovers from the durable receipt. Actual child-process death is tested locally. SQLite remains a single-host boundary, not distributed coordination.
- Existing generic Workbench HTTP delivery also looks for a receipt before fresh authorization. Its legacy retry behavior remains available for the original synthetic destination; the Salesforce application uses the bounded dispatcher.
- [UI integration](../src/signals/seller_api.py): authenticated delivery and read-only reconciliation, visible blocked/exhausted states, accurate destination labels and explicit software-fixture provenance. The local bridge remains for contract compatibility; it trusts its shared credential and is not a public approval service. Use the dispatcher launcher for native review.

## Metadata and review experience

[Source-format metadata](../salesforce/README.md) includes two objects, field definitions, unique external keys, insert/immutability validation rules, Integration/Reviewer permission sets, a review tab, list view and record layout. No Apex, Flow, trigger, external callout or automatic commercial action is included. The owner deployed it before this finishing review; deployed schema and three active validation rules were observed through authenticated read-only queries. This finishing review does not claim a new metadata deployment.

The integration has Create/Read on reviews, Read on the registry and API access. It cannot update/delete reviews or write the registry. The reviewer has Read/Edit on reviews, with only Review Status and Internal Notes editable; it cannot create/delete. Both require a minimum-access profile. Permission sets add access and cannot remove broad profile grants; preflight checks effective permissions. Review sharing is Public Read/Write in this isolated org so the reviewer can edit integration-created records; field/object grants still constrain access. Registry sharing is Public Read Only. This is an isolated demonstration sharing choice, not a production tenancy design.

The operator opens Synthetic Seller Reviews, checks the notice, approved draft, source claims in exact payload JSON, local account/proposed user and hashes, then marks Reviewed or Rejected with notes. Neither status executes a business action. Salesforce rejection is an internal review disposition; it does not automatically revoke Workbench approval. Approved content is read-only through field security and an immutability rule. Administrators can change metadata and remain outside that guarantee.

## Acceptance

[Native runner](../src/signals/salesforce_acceptance.py) verifies separate administrator, integration and reviewer identities, pinned environment, integration/reviewer permissions and absence of unrelated Account write rights. The administrator is an environment/global-visibility observer only. It uses a clearly handwritten proposal, the existing approval path and bounded dispatcher to test:

1. Real POST response discarded by the client after success, followed by receipt recovery.
2. Repeat dispatch and an actual duplicate POST rejected by the unique key; exactly one matching record.
3. A mismatched mapping rejected by the server validation rule.
4. Integration update/delete and registry write require restricted effective CRUD before/after, an observed rejection and unchanged SOQL snapshots of business content/modification audit fields. Generic entity rejections are explicitly unattributed; unrelated validation/API errors cannot pass. Reviewer payload mutation requires a specific permission error. Reviewer create uses independently checked no-Create rights plus zero matching probe records and an unchanged global record set. Its POST rejection is recorded accurately; the generic error alone does not prove a permission denial. Duplicate/validation/API-limit responses cannot pass that experiment.
5. Reviewer read/status edit persists; approved payload and mappings remain unchanged afterward.

Controlled acknowledgement loss models client-side response loss after a real response, not a vendor outage. Concurrent creation and process death are locally tested; native concurrent/process-death experiments are not implied. Use a fresh private output directory and new run ID for every new baseline acceptance. An explicitly selected eligible partial run can instead resume only its remaining mutation probes with `--resume-from`: it checks prior approval/receipt, run identity, completed experiments and compatible source fingerprints, and never POSTs. Prior failures retain their original status and source version; the continuation names inherited experiments and the prior verification hash. The runner allows at most 100 requests per identity, retains failed evidence and exits nonzero on failure. No bulk workload or capacity benchmark is required.

See [owner handoff](salesforce-owner-handoff.md), [evidence procedure](salesforce-evidence.md), and [local results](evidence/salesforce-local/README.md).

Salesforce documents Developer Edition support in its [REST authentication quick start](https://developer.salesforce.com/docs/platform/api-rest/guide/quickstart-oauth.html) and [Developer org overview](https://help.salesforce.com/s/articleView?id=000382500&language=en_US&type=1). Its [environment guard example](https://admin.salesforce.com/blog/2024/manage-permissions-in-a-sandbox-with-a-screen-flow-how-i-solved-it) uses IsSandbox and OrganizationType. Delivery follows [POST create](https://developer.salesforce.com/docs/platform/api-rest/guide/resources-sobject-basic-info-post.html) and [external-ID GET](https://developer.salesforce.com/docs/platform/api-rest/guide/resources-sobject-upsert-get.html).

## Boundaries

Local emulation is not native execution. The isolated org, deployed schema and native preflight are established; the corrected full acceptance matrix and genuine native screenshots remain incomplete. No client deployment, revenue uplift, independent seller usefulness, production throughput or universal exactly-once guarantee is claimed. One content key is unique; different approved content can create different review records. The prior genuine Qwen3-14B evaluation remains separate and has not been rerun or relabelled.
