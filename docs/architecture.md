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

The synthetic CRM uses external IDs, owned-field projection, revision preconditions, owner protection, durable idempotency receipts and independent current-state reconciliation. It retains unrelated sales fields. Real Salesforce/HubSpot adapters would need platform-specific object permissions, authentication, API quotas, conflict semantics and sandbox contract tests; these are deliberately not implied by a CRM-shaped local interface.

## Financial grains

**Opportunity → Fulfillment → Invoice → Payment allocation.** A fulfillment is one completed delivery of a commercial commitment associated with one opportunity. It can represent a delivered solution, an accepted engagement or an activated offering. This example requires completion before invoicing and collection; it does not model every enterprise billing arrangement. Closed Won alone creates neither a completed fulfillment nor cash. Completion is an operational source assertion, not accounting revenue recognition.

`opportunity` and `fulfillment` have revisioned states and immutable parent identities. Invoices and payment allocations are immutable source facts. A payment has exactly one invoice, that invoice one fulfillment, that fulfillment one won opportunity and account, all within one brand. The timeline must be won ≤ completed fulfillment ≤ invoice ≤ payment. Allocated cash may not exceed the invoice. Orphans and impossible economics block publication; missing marketing identifiers remain an explicit unattributed group rather than fabricated attribution.

The attribution rule selects the earliest observed campaign-bearing web or call touch at or before the won opportunity, tie-broken by event ID. Web touches need a reviewed session association. First touch is not necessarily the true first touch when instrumentation has gaps. Call events represent already consolidated logical calls, not raw call legs or phone-number matching. No call can fabricate an advertising click identifier.

The conversion event is **collected cash per payment allocation**, not a booked sale or invoice. A real integration must configure that distinct conversion action and avoid also importing the same value as another revenue event. Eligibility requires the attributed web touch's click ID, a 90-day window, current permission and valid financial lineage. Currency is CAD. Each allocation has a stable order ID. This is a vendor-neutral contract; [Google's upload documentation](https://developers.google.com/google-ads/api/docs/conversions/upload-offline) describes additional live API requirements not implemented here.

## Model graph

Seven dbt models: `stg_events` → `dim_account`, `fct_opportunity`, `fct_fulfillment`, `fct_touch` → `fct_cash_lineage` → `mart_campaign_cash`. The mart aggregates invoice values at distinct invoice grain before joining campaign-level cash. It reports only invoices linked to cash in this source snapshot. Models rebuild fully; no incremental claim is made. A separate Python traversal derives expected account/fulfillment/invoice/allocation/touch relationships from source events and checks every output row.
