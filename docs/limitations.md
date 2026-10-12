# Claim boundaries

This implementation proves a coherent, locally executable commercial journey, including a real browser, HTTP destination, process crash recovery and dbt consumption. It does not establish production capacity, customer outcomes, live vendor compatibility or cloud execution.

The selected scope deliberately leaves these boundaries visible:

- One local operator, SQLite and a serialized execution lane; no distributed worker leases, multitenant isolation service or enterprise availability SLA.
- Demo HTTP destinations run only on loopback and expose fixture fault controls through direct test database setup. They are trusted test services, not Internet-facing vendor emulators.
- Public intake needs rate limits, anti-abuse controls, domain/origin restrictions, consent-platform integration, retention/erasure policy and authentication design before production. Web signals are untrusted behavioral evidence, not proof of identity.
- Trusted source credentials establish source authority but are configured locally. Production secret rotation and managed identity are outside scope.
- No email/phone/domain matching. CRM supplies reviewed identity links. No fuzzy merge, call-leg deduplication, phone-number inference or automatic acquisition crosswalk.
- Enrichment provider results are synthetic, ingested through a typed authenticated interface. The selection/conflict/freshness workflow executes; no Clay, Apollo or ZoomInfo service is called.
- Transparent scoring is a rule system, not calibrated purchase probability. No measured conversion uplift or causal claim.
- First observed campaign touch may change after late data; no claim of loss-free web tracking. Existing external conversions are never silently rewritten after a changed attribution decision: destination order-ID conflicts require review.
- One currency, positive invoices/allocations, simple completed fulfillments. Refunds, credits, partial completion, recurring revenue and recognition are not implemented. Revenue Metrics Platform covers different commercial metric semantics.
- No Snowflake deployment or adapter is included. The new hiring evidence is acquisition-to-activation execution; local dbt is demonstrated, and existing portfolio work separately addresses Snowflake.
- Browser permission and canonical account permission are distinct. Stopping browser tracking does not erase history or retract past remote effects. A canonical privacy update must arrive separately.
- Dead/conflicting deliveries remain visible for operator review; the system does not guess how to repair vendor state. Lifecycle activation is a CRM projection with `nurture`, `qualified`, `customer` or `hold` state. The optional seller workbench also creates explicitly reviewed tasks in a separate authenticated synthetic CRM receiver; no outbound message is sent.
- Integrity hashes detect accidental changes within the trusted local environment, not attacks by the filesystem/database owner.

The [seller workbench](seller-workbench.md) executes real model inference when configured. Exact source quotations are validated, while interpretation and draft prose still require seller review. The synthetic benchmark measures finite task criteria, not population model accuracy, measured conversion uplift, independent human usefulness or production vendor compatibility. The published benchmark identifies pending human review explicitly. The scenario clock is fixed and visible; it does not simulate a continuously operated current customer estate.

