# Historical native Salesforce acceptance closeout

**Historical execution record.** This report preserves a prior acceptance stage, not the current GitHub status. See the [completed Salesforce review](../../../salesforce-finish-review.md) for the later result and publication.

Work was completed directly in the existing Windows project. The owner approved one bounded native matrix. One additional synthetic review was created; the original review, metadata, users, roles, mappings, private verification records and backups were preserved. GitHub publication remains a separate approval boundary.

## Executed Salesforce evidence

The original preflight passed with 10 requests; the original 23-request acceptance remains FAILED. A corrected 10-GET preflight also passed before the final mutation comparison change.

The approved correction attempt executed 35 requests and passed lost-acknowledgement recovery, repeat dispatch, duplicate-key rejection, server mapping validation, reviewer status edit, reviewer payload restriction and independent reviewer-create no-effect proof. It stopped at the integration PATCH error classification and remains FAILED.

The first continuation executed 19 requests and stopped because observational retrieval timestamps changed the whole-record hash. Two GET-only diagnostic reads established that only `LastViewedDate`/`LastReferencedDate` changed across retrievals. The final SOQL snapshots compare business content and mutation audit fields; changed content still fails local adversarial tests.

The final continuation PASSED with 34 requests, zero POSTs and zero administrator writes. Integration PATCH/DELETE and registry PATCH were rejected, independent restricted CRUD remained in force, before/after business/audit snapshots matched, exact approved content and Reviewed status were read back, one record matched the action key and the global review ID set remained unchanged. The earlier 35-request record supplies the named inherited experiments; its private verification hash is linked. This is a completed matrix across recorded stages and source versions, not one uninterrupted final-source run. All statuses remain intact in [native evidence](../../salesforce-native/README.md).

Generic `CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY` responses remain outside `permission_denied()`. They are accurately labelled unattributed rejections. Independent effective permissions and zero-effect evidence establish the tested restriction. No Apex triggers or active flows were found; three validation rules were present. The underlying generic vendor error cause is not established.

## Local verification and publication boundary

[The final verification record](verification.json) supplies the actual full-suite count, dependency/lint results, deterministic demo comparison, archived inference-summary recomputation, Markdown checks and source fingerprints. [The screenshot](contract-review.png) is real Chromium execution of the local contract workflow, explicitly labelled no inference; it is not a Salesforce UI screenshot.

All 385 pre-existing evidence/image files are preserved. The initial screenshot/upstream hash discrepancy is disclosed in [baseline provenance](../reviewer-create-fix/baseline-provenance.json). The original hashes are retained. The final ZIP and package manifest exclude private runtime, credentials, keys, backups, databases and raw logs; a separate private publication preview lists exact changes and privacy checks.

The README opens with the commercial problem, emphasizes exact approvals/reconciliation/restricted identities and distinguishes local tests, recorded inference, native preflight and the completed staged API matrix. No client outcomes, throughput guarantee, fresh model-to-Salesforce execution, native UI capture or hosted CI pass is claimed. At the time of this recorded stage, `main` remained at `f44134556d62129fcd20d2244f888a862c64cb89` and publication was still pending. The linked completed Salesforce review supersedes that stage's status.
