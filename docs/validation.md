# Validation and hostile review

`python scripts/verify.py` is the reproducible entry point. It executes dependency and lint checks, the complete pytest suite, actual Chromium, HTTP and dbt integration, then two independent full demonstrations. It compares the complete deterministic demo results, validates local Markdown links, records source hashes and regenerates the delivery manifest. A new workspace is used each time. [Actual local result](evidence/verification.json).

[Individual test results](evidence/tests.xml) and [executed dbt node results and dependencies](evidence/dbt-results.json) retain the underlying checks.

## Failure matrix

| Failure / invariant | Executable proof |
|---|---|
| Duplicate ID vs changed payload | `test_contracts.py::test_replay_and_changed_identity` |
| New event ID cannot duplicate business revision/payment/call | `test_contracts.py::test_new_transport_id_cannot_duplicate_entity` |
| Unsupported version, extra fields, PII, missing UTC, false permissions | Parametrized closed-browser contract tests |
| Browser cannot claim enterprise authority | API test supplies CRM event to public collector and missing bearer |
| Concurrent replay | Eight admissions across four threads converge on one source sequence |
| Bad identity association and commercial reparenting | `test_review.py` rejects session reassignment and opportunity account changes |
| Source priority, fit conflict and fallback | Decision tests preserve CRM facts; conflicting providers hold; fallback supplies missing fit |
| Signal freshness and replay spam | Intent/fit expires with clock advance; repeated pricing views do not increase score |
| Incorrect brand/territory/owner | Brand-scoped session and routing tests; existing mismatched owner held |
| Stale consent revision | Newer refusal survives delayed lower revision |
| Lost response, 429 and 503 | Real HTTP fault injection, durable reopen, one retained business effect |
| Process death after commit | Real Python subprocess exits86 after remote commit; reopened worker recovers receipt |
| Four failures exhaust retries | Explicit dead state and unresolved reconciliation, never reported as success |
| Consent changes after planning | Old work blocks; no remote effect |
| Remote ownership or revision race | CRM rejects owner conflict and stale revision; unrelated sales notes survive |
| Remote drift | Current CRM properties are compared independently with last applied projection |
| Financial lineage changes while queued | Conversion worker rechecks allocation graph and refuses invalid cash |
| Orphan, lost opportunity, overpayment, brand or timeline mismatch | Python traversal and actual dbt publication tests |
| Invoice/payment fanout | Exact independently known 12-account result: 8 invoices, 16 allocations, CAD5,000 |
| Earlier touch arrives late | Real dbt restatement equals a clean replay with reversed admission order; cash unchanged |
| Missing call click ID | Cash remains attributable to call campaign; conversion excluded without invented identifier |
| Conversion replay / remote key conflict | Stable allocation order IDs and durable payload-hash receipts |
| Invalid publication | Failing dbt preserves prior report; a changed report hash refuses the reader |
| Actual browser journey | Playwright clicks consent/pricing/sales contact, checks data layer, supplies authenticated CRM link, delivers CRM and conversions, executes dbt |
| Navigation and revocation | Campaign survives same-tab navigation; ads permission defaults denied; revocation clears local identifiers |
| Lost browser acknowledgement | Actual collector commits, simulated acknowledgement fails, browser retries the identical event ID; exactly one event persists |
| Qualified does not mean sold | An open qualified opportunity creates no financial allocations |
| Versioned enterprise B2B contract | Earlier wire and persisted contracts are refused; explicit fulfillment grain and sales-contact action are validated |
| Business-unit presentation | Harbour branding and collected brand/session context agree in a real browser |

## Independent checks

The 12-account fixture has four won/completed fulfillments, eight invoices and sixteen half-invoice payment allocations totalling exactly CAD5,000. Those values are asserted independently of generated output. The default 120-account run expands the same inspectable business cases; its reported totals come from sources, not target figures. Whole source generation and full demonstration outputs must reproduce exactly.

The SQL graph does not import Python-computed attribution or financial measures. Python traverses the original event graph independently, checks commercial constraints, and compares both every allocation lineage row and every campaign metric. This catches fanout, dropped cash and wrong attribution that a row count alone would miss.

## Hostile review resolutions

- **“This is another control-plane project.”** The new proof is a real browser/customer signal transformed into fit, intent, route, CRM state and cash feedback. Recovery controls support that journey; they are not the main artifact.
- **“The adapters are only function mocks.”** The destination runs an actual HTTP service with separate durable storage. Timeout-after-commit, version conflict and process death cross that network boundary.
- **“The metrics reuse the same formulas.”** dbt computes from raw source envelopes; an independent graph traversal validates allocation lineage and campaign totals.
- **“A late financial error can slip into an already queued conversion.”** Dispatch revalidates the full financial relationship and eligibility before a new remote effect.
- **“A new source revision can silently move money between customers.”** Opportunity-account and fulfillment-opportunity parent identities cannot change through revisions.
- **“A successful API response proves the CRM is right.”** Current-state reconciliation compares the owned field projection; unresolved work prevents a matched disposition.
- **“Browser consent grants permission to market to an account.”** Browser collection and canonical activation permission are distinct authenticated boundaries.
- **“The tools imply vendor production experience.”** The scope explicitly distinguishes local executable contracts, professional architecture patterns and unexecuted vendor services.

Remaining limits are intentional and listed in [limitations](limitations.md): positive cash only, simple rules, explicit CRM associations, no causal attribution, no distributed throughput claim and no cloud/vendor deployment. No GitHub-hosted result is claimed for this local delivery.

The README Mermaid was parsed and rendered in Chromium using a local Mermaid 10.9.3 bundle; [render evidence](evidence/diagram-check.json) records the source and bundle hashes. To reproduce that optional presentation check, supply the same bundle to `python scripts/render_diagram.py --mermaid-js PATH`. The bundle is not vendored into the repository.
