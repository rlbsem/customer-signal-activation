# Seller workbench delivery status

Baseline: `b655ba8b526a0f3d97a4edc20902a3b4ed652b50`, the latest GitHub main when this work began.
Feature branch: `feature/evidence-grounded-seller-workbench`.

1. Evidence foundation: scoped authenticated documents, freshness, authoritative account state and actual structured model adapter implemented.
2. Review and execution: immutable generation records, cached inference, content-bound approval, rejection, current-evidence checks, authenticated HTTP tasks and receipt reconciliation implemented.
3. Application and analytics: seller workspace, source citations, editable draft, execution history, recorded evaluation explorer and separate operational dbt models implemented. The browser has executed a live brief, approval and task delivery. New software regression tests pass; full final verification follows the benchmark.
4. Evaluation and delivery: genuine Qwen3-14B inference is available locally. Development grounded workflow passed 6/6 cases. The larger frozen 60-case, two-seed comparison is running, with resumable traces. Final results, screenshots, source-bound verification and package hashes must be generated before final review.

If execution is interrupted, use the [run instructions](seller-workbench.md) to start the same pinned model and resume `python scripts/evaluate_seller.py --cases 60 --repeats 2`. It will reuse a trace only when its configuration hash matches. Do not edit or substitute outputs to make the evaluation pass. Then run `python scripts/validate_seller_evidence.py`, inspect the application and capture genuine screenshots, run `python scripts/verify.py` and `python scripts/package.py`. Update this status from actual results and open a pull request. Merge requires the repository owner's approval.

Human usefulness assessment, actual vendor compatibility and measured commercial uplift are separate from software and finite synthetic evaluation. No such results are asserted.
