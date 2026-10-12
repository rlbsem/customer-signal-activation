# Repository map

| Path | Responsibility |
|---|---|
| `web/` | Consent-aware intake plus an authenticated seller workspace and recorded model comparison |
| `src/signals/contracts.py`, `api.py`, `store.py` | Closed source contracts, authenticated admission and durable event identities |
| `src/signals/decision.py` | Fit, intent, provenance, consent, lifecycle and brand/territory routing |
| `src/signals/finance.py` | Independent commercial relationship validation and conversion eligibility |
| `src/signals/worker.py`, `remote.py`, `reconcile.py` | Real HTTP delivery, persisted CRM/conversion effects and reconciliation |
| `src/signals/analytics.py`, `dbt/` | Real dbt graph, independent row oracle and gated publication |
| `src/signals/fixtures.py` | Deterministic synthetic sources |
| `src/signals/seller.py`, `seller_api.py` | Source-bound model proposals, exact review content, authority checks and authenticated CRM task delivery |
| `src/signals/seller_evaluation.py` | Explicit finite-scenario proposal rubric and comparative baselines |
| `src/signals/seller_analytics.py`, `seller_dbt/` | Generation and action grains, conserved operational metrics and separate dbt quality gates |
| `docs/evidence/seller/` | Actual inference traces, original failed evaluation archive, application records and runtime provenance |
| `scripts/` | Demo, browser server, operator commands, verification and clean packaging |
| `tests/` | Failure cases, browser integration, HTTP recovery and dbt publication gates |
| `docs/evidence/` | Generated business report, source-linked results and local validation record |
| `.github/workflows/verify.yml` | Hosted execution definition; status must be checked independently |

