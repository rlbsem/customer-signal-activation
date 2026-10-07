# Repository map

| Path | Responsibility |
|---|---|
| `web/` | Actual consent-aware browser intake and GTM-compatible event objects |
| `src/signals/contracts.py`, `api.py`, `store.py` | Closed source contracts, authenticated admission and durable event identities |
| `src/signals/decision.py` | Fit, intent, provenance, consent, lifecycle and brand/territory routing |
| `src/signals/finance.py` | Independent commercial relationship validation and conversion eligibility |
| `src/signals/worker.py`, `remote.py`, `reconcile.py` | Real HTTP delivery, persisted CRM/conversion effects and reconciliation |
| `src/signals/analytics.py`, `dbt/` | Real dbt graph, independent row oracle and gated publication |
| `src/signals/fixtures.py` | Deterministic synthetic sources |
| `scripts/` | Demo, browser server, operator commands, verification and clean packaging |
| `tests/` | Failure cases, browser integration, HTTP recovery and dbt publication gates |
| `docs/evidence/` | Generated business report, source-linked results and local validation record |
| `.github/workflows/verify.yml` | Hosted execution definition; status must be checked independently |

