# Lifecycle Operations

Three competing lifecycle journeys run inside Customer Signal & Activation: trial onboarding, quiet-trial assistance and customer expansion education. The new module uses synthetic person-level identities and preferences; account consent cannot authorize a person's marketing action.

## Run

From a Python 3.12 environment installed using the repository requirements:

```text
python scripts/lifecycle.py --workspace .local/lifecycle --port 8570
```

Open http://127.0.0.1:8570 and enter the temporary operator token printed by the launcher. The API and independent acceptance destination bind to loopback. They never send email. Select `synthetic-0000`: quiet-trial assistance wins over onboarding because its priority is 30 versus 20. An active opportunity places expansion education on owner review. These are finite demonstration policies.

Approve the winning action, lose its acknowledgment, then reconcile. One receipt should be observed. Advance 24 hours to make room for onboarding. Revoke marketing permission before a new action to block it. Record conversion to cancel unsent trial actions. Inspect current source revisions, durable timers and the decision timeline in the detail panels.

## Authority and storage

`signals.lifecycle` uses a separate SQLite database with WAL and serialized write transactions. Existing `signals.remote.connect`, canonical payload hashing, `Refused`, loopback HTTP harness and independent receipt patterns are reused. The existing account projection dispatcher is intentionally not used to infer person authorization. No existing native adapter or its evidence is regenerated.

- CRM owns explicit brand/person/account mapping, sales owner, commercial status and conversions.
- Product owns trial starts, activity and observation coverage. No records is not proof of inactivity.
- Preferences own email/marketing permission. Revisions win within source event identity before effective-time evaluation.
- Immutable journey versions own the three finite priorities, waits and contact limits. A registered new version can pause selected journeys; explicit migration changes enrollment epoch and fences old actions.
- The separate HTTP destination owns durable acceptance receipts. It is a local emulator, not a marketing vendor or email delivery service.

The source ledger is unique at brand/source/event/revision with immutable fingerprints and event/observation times. Enrollments are unique at brand/person/journey/entry identity. Actions are unique at enrollment/epoch and bind exact payload, source evidence and reviewed hash. History is append-only. Analytics exports enrollment, action, event and history tables to a separate DuckDB database; SQL cannot authorize actions.

## Contact and recovery contract

All three journeys share brand/person contact limits: one accepted or unresolved action in a rolling 24 hours and two in seven days. Unknown or exhausted outcomes retain capacity indefinitely until safely reconciled. Synthetic local quiet hours are 20:00–09:00 in the person's IANA time zone. UTC instants map into local time, so ambiguous/nonexistent local wall times are never invented.

Reservation commits before HTTP. Receipt lookup precedes current authorization, so a committed action may be historically reconciled after revocation without granting a new POST. This destination guarantees action-key idempotency and exact payload comparison. Other destinations would require their own contract and native acceptance. HTTP errors never establish that no effect occurred. Retryable 429 results have finite exponential backoff and stop after three attempts. Unknown 5xx/transport outcomes remain uncertain.

SQLite serializes reservations across workers. A second action cannot occupy the same final slot; simultaneous retries of the same key may issue multiple requests to the idempotent destination but cannot create multiple effects. This is not a distributed exactly-once guarantee. A real subprocess termination test exits after destination acceptance and before local acknowledgment, then reopens the durable state and independently recovers one receipt.

Changes to source evidence clear old approvals. Conversion exits preserve historical receipts and cancel unsent trial actions. A policy migration refuses unresolved reservations, increments the epoch and requires a new approval. Version changes do not undo accepted messages. Operator hold is distinct from rejection by business policy.

## Reporting and reproduction

```text
python -m pytest tests/test_lifecycle.py -q
python scripts/verify_lifecycle.py work/new-lifecycle-run docs/evidence/new-lifecycle-run
```

Use a fresh working directory and output directory for each evidence run. The verifier executes real HTTP actions for all three journeys, independently reads destination receipts, drives the operator browser on desktop/mobile, runs dbt, applies a backdated conversion correction, and compares incremental results with an independent full build. A Python oracle separately checks action rows, conversion revision winners and journey aggregates. The 1,200-person scenario is deterministic operational data, not a performance benchmark. The 12-person reference has explicit expected eligibility reasons in the regression suite.

The five dbt models expose action grain, conversion-revision grain, immutable transitions, journey totals and cohort-day enrollment/transition counts. Attempts are aggregated at action grain. Accepted messages, conversions and financial revenue are never equated. No experimentation or synthetic uplift is introduced.

[Execution record](evidence/lifecycle/execution.json) · [Executed tests](evidence/lifecycle/tests.xml) · [Desktop](evidence/lifecycle/lifecycle-desktop.png) · [Mobile](evidence/lifecycle/lifecycle-mobile.png).

## Boundaries and development observations

This is bounded local execution with an explicit operator clock, not an always-running managed scheduler. Native Salesforce/Snowflake and model evidence elsewhere in the repository belong to their original runs. No native marketing tenant entitlement is established by existing Salesforce Developer Edition authentication; no optional vendor execution was attempted.

The first hosted lifecycle job also exposed a missing parent `work` directory on a clean checkout; the workflow now creates it before pytest. Observed development failures included restricted sandbox sockets, an unquoted SQL `at` column, and audit hashes overflowing the mobile timeline. Local HTTP was rerun with socket access, SQL columns were quoted, and long audit text was made wrapping. Browser acceptance was tightened to approve the actual winning journey and wait for observed state before capture.

Residual production boundaries include the non-atomic external I/O boundary, one local SQLite execution domain, explicit clock driving, finite journey templates, and no native platform or deliverability acceptance. A revocation arriving after the final current-state check cannot atomically recall an in-flight remote request. The local contract does not claim that capability.
