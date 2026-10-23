# Lifecycle orchestration and experiment measurement — executed evidence

The customer-signal platform now includes three governed lifecycle journeys and an experiment layer that answers two separate questions: **Was an approved action delivered safely?** and **Did assigned treatment outperform a properly enforced holdout?**

The code executes locally with synthetic people and simulated commercial outcomes. Tests use actual processes, durable SQLite stores, an independent loopback HTTP destination, real DuckDB/dbt builds and browser interaction. This is not a marketing-platform deployment or a claim of customer revenue lift.

## What executes

| Capability | Verified behavior |
|---|---|
| Lifecycle journeys | Trial onboarding, quiet-trial assistance and expansion education with person-level preferences, eligibility, timers, arbitration and conversion exits |
| Action authorization | Current consent, brand, CRM owner, eligibility, contact limits and exact human approval checked before dispatch |
| Recovery | Two independent local HTTP effects verified after a lost acknowledgment and actual worker-process termination, with no duplicated receiver effects |
| Experiment controls | Immutable seeded person-level treatment/holdout assignments; holdouts enforced across competing journeys, not merely labeled in reporting |
| Outcomes | Assigned denominator retained; incomplete windows report Unknown; late outcome corrections and late receipt observations respect reporting cutoffs |
| Measurement | Nine dbt models, 13 data tests, independent Python reconciliation and corrected incremental/full-build parity |
| Interface | Responsive lifecycle operator and Experiment & Outcomes workspace, with actual browser execution and desktop/mobile captures |

## Recorded verification

- **443 tests passed** at the final experiment source revision; corresponding Windows and Linux GitHub checks completed successfully.
- **12-person reference:** six treatment and six holdout assignments; two independent accepted effects. Four source conversions were revised to three after a late correction.
- **1,200-person reproducibility:** 627 treatment and 573 holdout assignments, with 399 corrected conversions. That run does **not** make 1,200 remote HTTP submissions or establish throughput.
- **Source integrity:** PR #9 verified preservation of 470 earlier evidence/image artifacts and 676 package fingerprints.

**[Lifecycle implementation and operator procedure](lifecycle.md)** · **[Experiment contracts and model grains](lifecycle-experiments.md)** · **[Final execution record and screenshots](evidence/lifecycle-experiment/historical-receipt-fix/README.md)** · **[Metric contract](lifecycle-experiment-contract-v1.json)**

## Execution boundaries

The experiment has synthetic assignment, conversion and opportunity fixtures; its model compares those sources accurately but does not demonstrate real incremental conversion, customer communication or revenue. Explicitly linked opportunity values are simulated pipeline, not invoiced or collected cash. The existing native Salesforce–Snowflake integration and Qwen seller-agent evidence are separate executions, not one continuous customer lifecycle deployment.

The historical receipt-fix evidence directory retains the final audited execution; prior experimental runs remain available at their own recorded revisions. This entry point distinguishes the current implementation from those preserved debugging stages.
