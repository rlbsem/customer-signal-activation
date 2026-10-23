# Seller workbench implementation record

The seller workbench links scoped account documents and authoritative CRM context to model-assisted research, human review, controlled internal task delivery, and operational analytics. Its primary engineering distinction is the separation of **advice, approval, current source authority, and verified execution**.

## Implemented boundaries

1. **Evidence ingestion:** scoped authenticated documents, freshness checks, authoritative account state, and a structured local-model adapter.
2. **Review and execution:** immutable generation records, content-bound approval or rejection, current-evidence rechecks, authenticated HTTP task submission, and independent receipt reconciliation.
3. **Application and analytics:** operator workspace with source citations, editable drafts, review and execution history, evaluation explorer, and dbt operational models. The recorded browser run includes three model-generated briefs, an edited approval, and one reconciled task delivery.
4. **Model evaluation:** genuine local Qwen3-14B inference. The saved 60-case, two-seed comparison reports 120/120 passing mechanical proposal checks for the grounded workflow, versus 81/120 for the simple LLM and 60/120 for the governed template. The earlier failing evaluation is retained. **Those scores measure the published rubric, not independent human usefulness or semantic truth.** See the [source-support review](seller-review-notes.md) for a recorded unsupported implication.

## Reproduce and inspect

Use the [seller workbench procedure](seller-workbench.md) to run the pinned model and `python scripts/evaluate_seller.py --cases 60 --repeats 2`. Saved traces are reused only when configuration hashes match. Use a fresh output directory to generate new inference. Run `python scripts/validate_seller_evidence.py`, `python scripts/verify.py`, and `python scripts/package.py` to inspect the published software and evidence.

[Architecture](architecture.md) · [Original evaluation and failure traces](evidence/seller/first-pass-report.md) · [Source-support review](seller-review-notes.md) · [Acceptance and authority](seller-authority.md)

The local evaluation, operator review, and synthetic workflow records do not measure live seller productivity, pipeline lift, or customer revenue. Vendor compatibility and production operation require separate acceptance.
