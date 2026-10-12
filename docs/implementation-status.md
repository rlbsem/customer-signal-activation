# Seller workbench delivery status

Baseline: `b655ba8b526a0f3d97a4edc20902a3b4ed652b50`, the latest GitHub main when this work began.
Feature branch: `feature/evidence-grounded-seller-workbench`.

1. Evidence foundation: scoped authenticated documents, freshness, authoritative account state and actual structured model adapter implemented.
2. Review and execution: immutable generation records, cached inference, content-bound approval, rejection, current-evidence checks, authenticated HTTP tasks and receipt reconciliation implemented.
3. Application and analytics: seller workspace, source citations, editable draft, execution history, recorded evaluation explorer and separate operational dbt models implemented. The browser has executed three live briefs, an edited approval and one reconciled task delivery. Operational dbt build and conservation tests pass.
4. Evaluation: genuine Qwen3-14B inference executed locally. The delivered 60-case, two-seed regression comparison passes 120/120 grounded proposal checks, versus 81/120 for the simple LLM and 60/120 for the governed template. The original failed evaluation is retained in a verified archive. Source-bound citation decoding and explicit attention to the customer's operational friction address the observed defects. Final screenshots and full source-bound verification are generated for pull-request review.

To reproduce or extend the work, use the [run instructions](seller-workbench.md) to start the same pinned model and run `python scripts/evaluate_seller.py --cases 60 --repeats 2`. Stored traces are reused only when configuration hashes match; use a fresh output directory for new inference. Do not edit or substitute outputs to make evaluation pass. Run `python scripts/validate_seller_evidence.py`, inspect the application, run `python scripts/verify.py` and `python scripts/package.py`. Merge requires the repository owner's approval.

Human usefulness assessment, actual vendor compatibility and measured commercial uplift are separate from software and finite synthetic evaluation. No such results are asserted.
