# Local Salesforce acceptance revision — delivery

Completed October 15, 2026. Base: `rlbsem/customer-signal-activation` at `f44134556d62129fcd20d2244f888a862c64cb89`. This is a complete local repository package; no commits, pushes or pull requests were created.

## Implemented

- Explicitly approved pinned sandbox **or Developer Edition**, verified against authenticated Organization ID, IsSandbox and exact OrganizationType. Ordinary production and mismatched/unapproved configurations are rejected.
- Source-format Salesforce metadata: two synthetic objects, unique external keys, lookup/display/review fields, three validation rules, scoped Integration/Reviewer permission sets, tab/list view/layout. XML and contracts were tested locally; native metadata compilation remains pending.
- Approved synthetic account/owner mapping, active registry/user validation and server-side mapping rule; review records only, with no real Account/Opportunity/Task mutation or messaging.
- Durable bounded dispatcher: historical receipt reconciliation before new-action authorization, process-death recovery, exact read-back, four-attempt/one-hour defaults, retry scheduling and exhaustion with explicit read-only operator recovery.
- Reproducible native acceptance runner, identity/role/environment preflight, duplicate-key, client-lost-acknowledgement, permission-denial, server-mapping and final read-back experiments. The runner was tested over local emulated HTTP, not Salesforce.
- Existing browser workbench integration and operator-facing Salesforce review metadata, precise owner setup and evidence-capture instructions.

## Executed results

| Check | Result |
|---|---|
| Complete regression suite | 166 passed; zero failures/errors/skips; 203.67 seconds |
| Salesforce contract/acceptance cases included above | 80 passed |
| Dependency consistency and full source/test/script Ruff checks | Passed |
| Chromium operator workflow | Passed; screenshot explicitly labels local contract emulation and no inference |
| Actual child-process death | Reopened worker recovered one persisted local remote record; no second POST |
| Two independent source-to-cash demos | Identical: 120 accounts, 1,070 events, CAD55,300.00 cash, 80 CRM projections, 40 conversions |
| Prior evidence/image files | 379 byte-identical |
| Archived seller traces | 360 traces validated; summaries recomputed |
| Internal Markdown file paths | 60 checked |
| Final tested-source fingerprints | Matched the packaged implementation |
| Salesforce deployment/execution, new LLM inference, GitHub CI | Not executed |

There was one pre-existing AnyIO/Starlette deprecation warning. No cloud/API charges, credential changes or public GitHub writes occurred.

## Next boundary and precise completion steps

Create an isolated free Developer Edition org and authenticate locally with the Salesforce CLI under alias `csa-demo-owner`. Provide the alias and explicit approval of the org ID; share no password/token/auth URL. The [owner handoff](../../salesforce-owner-handoff.md) has exact commands for the gated check-only/deployment, two restricted test identities, registry seed, private config and local token handoff. Available compatible free seats/API entitlement must be checked; no paid license is assumed.

Then run native preflight and acceptance into a fresh private output directory, inspect the actual Salesforce list/detail view, capture genuine redacted screenshots and review the sanitized evidence. The [evidence procedure](../../salesforce-evidence.md) defines what to retain and what must stay private. A fresh model-to-Salesforce run additionally needs the existing real local model server and a new human approval; the native delivery fixture is explicitly handwritten.

Use `python scripts/verify_salesforce.py` for this revision. It preserves prior archives. Review [the acceptance plan](../../salesforce-acceptance-plan.md) for exact controls and limitations. The original archived evidence refers to its original source version; the new verification record fingerprints this candidate separately.

## Existing files changed from the pinned public base

- `.gitignore`
- `README.md`
- `package-manifest.json`
- `scripts/package.py`
- `src/signals/seller.py`
- `src/signals/seller_api.py`
- `web/seller.html`
- `web/seller.js`

Additional files implement the Salesforce contract/dispatcher/runner, local tests, deployment/operator tooling, metadata and documentation. The root package manifest lists every delivered file and SHA-256 (excluding itself). Archived financial/inference evidence was preserved unchanged.
