# Historical Salesforce reviewer-create correction

**Historical execution record.** This report preserves a prior acceptance stage, not the current GitHub status. See the [completed Salesforce review](../../../salesforce-finish-review.md) for the later result and publication.

The existing Windows project was reviewed and updated in place. No Salesforce deployment, user/permission change, additional native business write or GitHub publication was performed by this correction. Original private native runs, backups and prior evidence remain in place.

## Security correction

`CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY` is still excluded from the permission-error allowlist. The reviewer-create experiment separately proves effective no-Create permissions before/after, an unused probe key, unchanged complete global record IDs and zero matching effects. A generic HTTP 400 is recorded as an unattributed entity rejection; its error code does not establish the cause. Unexpected successful creation, unrelated failures, missing visibility, stale keys and permission drift fail the experiment.

The restricted integration/reviewer identities remain separate from the read-only administrator observer. The adapter verifies the pinned environment directly or consumes the live administrator's typed attestation; stale destinations cannot dispatch. Acceptance checkpoints survive failures, existing action keys stop the run before a new lost-ack experiment, and the CLI wrapper reads existing credentials in process memory without printing or persisting them.

## Actual executed results

| Check | Result |
|---|---|
| [Complete regression record](verification.json) | 190 passed; 0 failures, errors or skipped tests; 122.925 seconds |
| Salesforce contract/export cases included above | 104 passed; local HTTP emulation, not vendor business-write acceptance |
| Dependency consistency and Ruff | Passed |
| Chromium review workflow | Passed; [screenshot](contract-review.png) visually inspected and explicitly labelled local/no inference |
| Two independent commercial demonstrations | Equal: 120 accounts, 1,070 events, 5,530,000 cash cents, 80 CRM projections and 40 eligible conversions |
| Prior evidence | All 385 files present at the start of this review preserved unchanged |
| Recorded inference audit | 360 existing traces validated and summaries recomputed; no fresh inference or independent usefulness review claimed |
| Markdown file links | 81 checked during full verification; supplemental evidence links checked separately |
| [Corrected native preflight](../../salesforce-native/current/preflight-finish-review-final-02.json) | PASSED; 10 authenticated GET requests against the pinned Developer Edition and existing identities |
| Corrected full native acceptance | Not executed; owner approval required before additional live writes |
| Hosted GitHub CI for this correction | Not run at this archived correction stage |

One existing Starlette/AnyIO deprecation warning remains. A pre-existing upstream hash difference in `docs/images/browser-proof.png` is disclosed in [baseline provenance](baseline-provenance.json); the image's bytes did not change during this work. The original archive hashes are retained.

## Review and next boundary

The [native status](../../salesforce-native/README.md) retains the actual original preflight pass and 23-request acceptance failure alongside the new preflight. It does not upgrade the failed run into a pass. [The exact bounded live-operation plan](../../../salesforce-finish-review.md) requires owner approval. A full accepted release still needs that native matrix to pass, review of its sanitized evidence, separate GitHub publication approval and hosted checks. No new account setup, credential rotation or environment reset is required.

The README now exposes local, recorded-inference, native-preflight and incomplete-native-acceptance boundaries near the top. The architectural notes explain immutable content, separate identities, independent permission/effect evidence and failure recovery. Publication includes the existing local Salesforce extension plus this correction; private runtime, credentials, backups and raw logs are excluded.
