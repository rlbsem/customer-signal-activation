# Architecture and business contracts

## Three boundaries

The synthetic enterprise has two business units, Cedar Systems and Harbour Solutions, offering enterprise workflow solutions and technology-enabled business capabilities. The model does not assume subscriptions, residential consumers or a particular operating industry. The campaigns `enterprise-workflows` and `partner-referral` represent digital demand and partner-sourced sales conversations. ON/BC remain explicit Canadian sales territories, not service-area inference.

1. Browser collection accepts only `web` events. Other source kinds require server credentials whose mapped actor determines authority. Closed Pydantic contracts reject unknown fields/version, implicit integer coercion and missing UTC timestamps. Event IDs are immutable within a brand. Business entity/revision keys also refuse duplicate admissions under new transport IDs.
2. A SQLite transaction persists an immutable decision with its input watermark and a destination-specific outbox operation. Dispatch re-evaluates the relevant account at the dispatch clock and rechecks conversion lineage. Remote HTTP commits and local receipts cannot share a transaction, so recovery reads the same idempotency receipt before attempting another write.
3. The warehouse snapshots an event watermark, runs real dbt models/tests, compares allocation-level results to an independently implemented Python graph traversal, then promotes only if the source watermark is unchanged. Reader hashes reject an altered publication. The prior publication survives any gate failure.

## Identity and trust

Identity is `(brand, account)`; anonymous context is `(brand, session)`. A trusted CRM `link` event supplies an explicit reviewed association and evidence. A session cannot be reassigned. This is conservative deterministic association, not probabilistic entity resolution. Shared phones, domains and email strings never grant identity. Browser interest can be fabricated by a client and therefore cannot establish a sale, invoice, payment, account consent or enrichment authority.

The intake records sales-contact intent; it does not implement a personal-information contact form. Its standard `generate_lead` data-layer event represents that intent. No email, phone or name is accepted by the web contract. Click identifiers stay in the collector envelope, outside the tag-facing data layer. There is no external GTM container or GA4 property. The event/variable interface follows [Google's data-layer architecture](https://developers.google.com/tag-platform/tag-manager/datalayer); real tag deployment and Tag Assistant validation require a separately configured environment.

## Fit, intent and routing

Policy `fit-intent-route/v2` uses an explicit local clock:

- Fit: 30 points for at least 20 employees. A present CRM employee count wins. Otherwise the latest revision from each enrichment provider must be no older than 30 days. Primary precedes fallback. If fresh providers disagree across the fit boundary, hold the account; do not average the disagreement away.
- Intent: 30 for sales-contact intent, 20 for pricing interest, 20 for at least one qualified call, each counted once in the preceding seven days. Repeat clicks cannot multiply a feature. No future event enters a decision.
- A total of 60 qualifies for a handoff. Lower scores are nurture candidates. Any routing/conflict/permission hold excludes activation. Won opportunities move an eligible projection to customer, stopping prospect nurture.
- Cedar and Harbour each have explicit ON/BC owner routes. An existing different owner or unsupported territory blocks automated reassignment. There is no round-robin/capacity optimizer or ownership inference.

Source revisions outrank receipt order. Higher revisions with effective times after the review clock are not yet considered. Event history is retained, and new decisions are immutable. A late event can restate a later evaluation. This is current-state evaluation at an explicit clock, not the general bitemporal engine in Temporal Customer Audiences.

## Consent and delivery

Browser analytics/ads permission controls browser collection and identifier storage. Activation consent is independently owned by the privacy source and defaults to denied. Browser revocation clears local identifiers and stops new collection; it cannot automatically identify and revoke a canonical account without the separate trusted privacy event. No legal consent-compliance certification is implied.

The worker holds a single local write transaction during bounded HTTP operations. Privacy admission and dispatch are serialized in that local lane. A revocation after an already committed remote effect cannot undo that effect; recovery records what happened. A fresh hold projection can stop nurture. External deletion/retraction is not implemented. Receipt recovery precedes consent rechecking so an already committed historical effect is never misreported as unsent.

The original synthetic CRM uses external IDs, owned-field projection, revision preconditions, owner protection, durable idempotency receipts and independent current-state reconciliation. It retains unrelated sales fields. These projection semantics are not assumed to exist automatically in a vendor API. The separate Salesforce adapter below implements a narrower create-only review-record contract; it does not project these fields into real Accounts or Opportunities. No HubSpot integration is claimed.

### Native Salesforce review boundary

Salesforce receives an exact approved recommendation in `Seller_Action__c`, linked to an explicitly approved synthetic registry row and active proposed user. A unique external key binds the canonical content. Create acknowledgements require exact read-back; a durable local journal reconciles uncertain historical effects before authorizing any new create. Current consent, evidence and owner mapping still gate new effects. Retry budgets are bounded, and an exhausted record requires an explicit read-only operator reconciliation.

Restricted integration/reviewer identities verify their authenticated org/user IDs. An independently authenticated administrator verifies `Organization.IsSandbox` and `OrganizationType`, because the minimum-access identities cannot query Organization. The resulting in-process attestation must match the pinned approval; an adapter used without that attestation must perform its own authenticated environment query. Ordinary production editions and changed pins fail closed. The administrator transport permits GET only; no administrator credential is used for business writes.

Reviewers can read the record and edit review status/notes, but cannot create/delete records or change approved content. A rejected create response alone does not establish permission. The corrected acceptance probe checks effective `createable=false` before and after the POST, requires zero matching probe records, and compares administrator-visible record ID sets. Administrator custom-field access is neither assumed nor expanded. `CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY` remains a generic rejection with unattributed cause, outside the explicit permission-error allowlist. A duplicate, validation error, API limit, successful create or record-set change cannot pass this experiment.

Native preflight and the scoped delivery/security matrix have executed in Developer Edition. The original failed runs remain failed; a guarded continuation completed the remaining probes against the existing exact record. Mutation snapshots use SOQL to compare business content and modification audit fields without confusing read-observation timestamps with business changes. See [execution evidence](evidence/salesforce-native/README.md) and [the completion plan](salesforce-finish-review.md). This is a synthetic review workflow, not an autonomous outreach service, vendor throughput benchmark or client deployment.

## Financial grains

**Opportunity → Fulfillment → Invoice → Payment allocation.** A fulfillment is one completed delivery of a commercial commitment associated with one opportunity. It can represent a delivered solution, an accepted engagement or an activated offering. This example requires completion before invoicing and collection; it does not model every enterprise billing arrangement. Closed Won alone creates neither a completed fulfillment nor cash. Completion is an operational source assertion, not accounting revenue recognition.

`opportunity` and `fulfillment` have revisioned states and immutable parent identities. Invoices and payment allocations are immutable source facts. A payment has exactly one invoice, that invoice one fulfillment, that fulfillment one won opportunity and account, all within one brand. The timeline must be won ≤ completed fulfillment ≤ invoice ≤ payment. Allocated cash may not exceed the invoice. Orphans and impossible economics block publication; missing marketing identifiers remain an explicit unattributed group rather than fabricated attribution.

The attribution rule selects the earliest observed campaign-bearing web or call touch at or before the won opportunity, tie-broken by event ID. Web touches need a reviewed session association. First touch is not necessarily the true first touch when instrumentation has gaps. Call events represent already consolidated logical calls, not raw call legs or phone-number matching. No call can fabricate an advertising click identifier.

The conversion event is **collected cash per payment allocation**, not a booked sale or invoice. A real integration must configure that distinct conversion action and avoid also importing the same value as another revenue event. Eligibility requires the attributed web touch's click ID, a 90-day window, current permission and valid financial lineage. Currency is CAD. Each allocation has a stable order ID. This is a vendor-neutral contract; [Google's upload documentation](https://developers.google.com/google-ads/api/docs/conversions/upload-offline) describes additional live API requirements not implemented here.

## Model graph

Seven dbt models: `stg_events` → `dim_account`, `fct_opportunity`, `fct_fulfillment`, `fct_touch` → `fct_cash_lineage` → `mart_campaign_cash`. The mart aggregates invoice values at distinct invoice grain before joining campaign-level cash. It reports only invoices linked to cash in this source snapshot. Models rebuild fully; no incremental claim is made. A separate Python traversal derives expected account/fulfillment/invoice/allocation/touch relationships from source events and checks every output row.
