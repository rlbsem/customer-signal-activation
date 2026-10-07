# Operations

## Reproduce

Install Python 3.12, the exact `requirements.lock`, and the editable project from its repository root. Browser tests require Playwright Chromium. Run `python scripts/verify.py` for the complete path. Run `python scripts/demo.py --workspace work/another-demo` for a new asserted business run. Workspaces must not already exist; nothing is reset automatically.

`python scripts/serve.py --workspace work/intake` starts a browser intake on loopback port 8522 by default. `--port` changes it. The printed path is the source SQLite database. The intake page uses relative same-origin HTTP calls and no embedded enterprise credential.

## Server source API

This release uses source `schema_version: 2`, application version 2.0.0 and policy `fit-intent-route/v2`. The renamed sales action and commercial-fulfillment fields are a breaking wire-contract change; earlier envelopes and databases are refused. Create a new workspace and regenerate sources. No in-place history rewrite or migration is performed. The policy thresholds, source authorities, economic amounts and recovery semantics are unchanged.

`POST /collect` accepts only the web envelope documented by `src/signals/contracts.py`. `POST /events` requires a bearer token mapped to `crm`, `privacy`, `enrichment`, `telephony`, `operations` or `finance`. `GET /status` requires an `operator` token. Set `SIGNALS_TOKENS` to a JSON object mapping local tokens to those actors; the default exposes no authenticated writes. Never place those values in browser code. API documentation is at `/docs`.

`schema_version`, `event_id`, `brand`, `kind`, `occurred_at` and `data` are required. Each kind has a closed data contract. `occurred_at` must carry a UTC offset. The collector assigns receipt time. A replay of the same event identity returns its original sequence; changed payloads or duplicated entity revisions reject with HTTP422. The demo fixture module is an executable example of all contracts.

For review and controlled execution use `python scripts/operate.py --help`. `plan` persists current decisions; `deliver` drains only currently due work; `conversions` plans financially eligible allocations; `reconcile` compares remote state; `build` runs the dbt publication gate. An explicit UTC `--as-of` makes policy evaluation reproducible. The demo uses March31,2026; live browser signals require an appropriately current clock.

## Failure recovery

| State / observation | Action |
|---|---|
| `pending` | Deliver due work; each attempt checks current state |
| `uncertain` | Wait for `next_at`, then reconcile the original request key before any write |
| `blocked` / decision changed | Investigate source events, then plan a fresh account decision; financially eligible blocked conversion payloads can be re-bound to a fresh decision |
| `conflict` | Inspect sales ownership, revision or existing conversion order ID; do not delete the remote receipt or invent a new payment ID |
| `dead` | Four attempts exhausted. Reconcile remote state and investigate the endpoint before an operator-reviewed repair; no automatic reset command is supplied |
| Reconciliation mismatch | Compare expected owned properties with remote state. Preserve legitimate sales changes; correct the authoritative input rather than blindly overwriting |
| dbt/oracle failure | Inspect the candidate's `dbt.log`; fix the source relationship. The prior publication remains readable |

The local demo faults only its own synthetic destination. Do not point these tools at real accounts. Raw event IDs and payloads are retained for source investigation. Status exposes counts by destination/state and named exceptions. The generated report links every allocated cash row to account, opportunity, fulfillment, invoice and touch; use that path to investigate source loss rather than assuming a campaign is responsible for revenue.

## Packaging

`python scripts/package.py` creates a clean ZIP one directory above this repository. Its manifest covers every delivered file except the manifest itself. The script reopens the archive and checks exact membership and SHA-256 values. Databases, caches, environments, test workspaces and private audit/positioning material are excluded.
