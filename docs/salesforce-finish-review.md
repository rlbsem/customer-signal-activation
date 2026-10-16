# Finish review: reviewer-create acceptance

Work is performed directly in the existing Windows project. Existing `.bak` files, deployed metadata, users, permissions and private evidence are preserved. The folder is a source distribution without `.git`; the public baseline was independently read from `rlbsem/customer-signal-activation` main at `f44134556d62129fcd20d2244f888a862c64cb89`. No GitHub write has been made.

## Diagnosis

The original native preflight passed with 10 authenticated requests. The native acceptance attempt failed after 23 requests at `reviewer_create_permission_denial_not_established`. Its telemetry records `400 CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY`; it did not retain the response message. The trace also records a successful synthetic create with deliberately discarded acknowledgement, receipt recovery, duplicate rejection, mapping validation rejection, an allowed reviewer status edit and denied payload edit. These observations do not retroactively turn the incomplete run into a full pass.

Fresh GET-only diagnostics independently confirmed separate authenticated identities and pinned Developer Edition identity/type. Effective review permissions are Integration Create/Read without Update/Delete and Reviewer Read/Update without Create/Delete. One existing review record is present and Reviewed. Tooling queries found no Apex triggers, no active flows and three active validation rules. No debug log was available to explain the historical rejection. The exact cause therefore remains unconfirmed; a future response must be reported as observed rather than guessed from its code.

The administrator can query all record IDs but lacks FLS on the custom content fields. That does not require a permission change: the new no-effect audit queries standard `Id` only, verifies the administrator's global visibility, and uses the restricted integration identity for the exact action-key count.

Salesforce's [SOAP exception reference](https://resources.docs.salesforce.com/latest/latest/en-us/sfdc/pdf/apex_api.pdf) documents this code in its exception taxonomy. A code that appears in permission and save-processing contexts is insufficient to infer a precise rejection cause. The implementation deliberately keeps it out of `permission_denied()`.

## Correction and acceptance requirements

The reviewer-create experiment now requires all of:

1. Authenticated reviewer describe confirms the exact restricted CRUD/FLS contract before the POST and again afterward.
2. A fresh probe key has zero matching records before and after.
3. A separate administrator with verified global visibility observes the identical complete record-ID set before and after. Incomplete/oversized snapshots fail closed.
4. The response is either an explicit recognized permission rejection, or exactly HTTP 400 with `CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY`, reported as `generic_entity_rejection_cause_unattributed`. Unrelated errors cannot satisfy this requirement.

No generic code is promoted into proof of permission. The independent permission and no-effect evidence establishes the tested security contract. If a record is created, visibility is insufficient, permissions drift or the response is an API/session/validation failure, the check fails. Experiment checkpoints preserve completed observations even if a later check fails; overall acceptance remains FAILED until the entire matrix passes.

The adapter's direct environment check has been restored as a fallback when no live administrator attestation is supplied. Three authenticated identities remain separate. CLI credential handling uses Salesforce's supported `org auth show-access-token` command, with output captured in process memory. Modern `org display` output is redacted and must not be scraped as a token. See [Salesforce's authentication-secret guide](https://developer.salesforce.com/docs/platform/sfdx-dev/guide/sfdx-dev-auth-view-secrets.html).

## Approved live operations and recorded execution

The owner explicitly approved the operations below after local verification. Read-only preflight and collision checks ran first. One fresh review was created. The original reviewed record and failed runs are retained; no user/permission/metadata changes occurred.

| Operation | Expected effect |
|---|---|
| Integration POST of one approved synthetic review | One new review record; acknowledgement deliberately discarded by the client |
| Receipt reconciliation and repeated dispatch | Read the same record; no second delivery create |
| Duplicate POST and mismatched-mapping POST | Rejected; no new records |
| Reviewer status/notes PATCH | Update only the new synthetic review's review status/notes |
| Reviewer payload PATCH and fresh-key create POST | Rejected; independent rights and no-effect evidence retained |
| Integration PATCH and DELETE of that new review | Denied; PATCH proposes the existing subject value |
| Integration registry PATCH | Denied; proposes the existing `Active=true`, avoiding a deliberate deactivation |
| Final read-back/counts | Same exact approved content and one baseline record for the run key |

No metadata deployment, user/permission changes, real Account/Opportunity/Task mutation, outreach, deletion cleanup, paid resources or GitHub publication is included. The administrator client makes GET requests only. Unexpected rights or effects stop the run and require investigation, never automatic cleanup.

Read-only command (already executable with the existing CLI logins):

```text
python scripts/run_salesforce_acceptance.py preflight --config .local/runtime.json --output .local/preflight-finish-review-final
```

Recorded initial command (already executed; do not reuse its existing output directory):

```text
python scripts/run_salesforce_acceptance.py acceptance --config .local/runtime.json --output .local/acceptance-finish-review-01 --run-id finish-review-01 --execute-approved-synthetic-writes
```

If a run ID already created a baseline record, the runner stops before a new write and requests a fresh ID. Existing state is not reset or silently adopted as a new lost-acknowledgement experiment. A failure retains its private checkpoints and telemetry.

### What actually executed

The approved attempt made 35 authenticated requests. Lost acknowledgement, receipt recovery, repeated dispatch, duplicate rejection, server mapping rejection, allowed reviewer status edit, denied payload edit and the strengthened reviewer-create contract passed. It then stopped at integration PATCH classification because Salesforce returned the same generic entity rejection. The run remains FAILED.

A guarded continuation uses the original private action/receipt and explicit `--resume-from`. It validates the prior run ID, approval audit, eligible completed checkpoints, native provenance and source compatibility. All business/adapter/metadata fingerprints must match; only the enumerated acceptance, export and wrapper/verifier files may differ. It verifies the exact existing receipt before remaining mutations, compares global record sets and never POSTs. This does not rerun or relabel historical experiments.

The first continuation made 19 requests and failed its full-response hash check. Two further GET-only diagnostic requests independently established that successive retrievals changed only `LastViewedDate`/`LastReferencedDate`. The final comparison uses explicit SOQL projections of all review/registry content and modification audit fields, including `LastModifiedDate` and `SystemModstamp`. Observation timestamps are outside that comparison. Salesforce documents that [SOQL queries do not update MRU](https://developer.salesforce.com/docs/platform/api-rest/guide/headers-mru.html). An altered business field or modification audit value still fails local adversarial tests.

The final continuation made 34 requests and PASSED: integration PATCH rejected with generic `CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY`, DELETE rejected with `INSUFFICIENT_ACCESS_OR_READONLY`, registry PATCH rejected with the generic code, independently restricted CRUD remained unchanged, business/audit snapshots matched, exact content/status read-back passed and the global review record set was unchanged. The generic rejection's underlying vendor cause remains unattributed; message hashes are retained, not raw vendor bodies.

```text
python scripts/run_salesforce_acceptance.py acceptance --config .local/runtime.json --output .local/acceptance-finish-review-continuation-02 --run-id finish-review-01 --resume-from .local/acceptance-finish-review-01/verification.json --execute-approved-synthetic-writes
```

That command is an execution record, not an instruction to repeat writes. [Sanitized stage records](evidence/salesforce-native/README.md) retain every status, source fingerprint and the continuation's reference to the prior verification SHA-256. The completed API matrix combines experiments from two source versions; no single uninterrupted final-source run, native UI screenshot or fresh model-to-Salesforce execution is claimed. The additional unsuccessful continuation remains visible.

## Publication plan — separate approval required

The prepared publication adds the existing local Salesforce extension plus this correction to the current public baseline, updates README/architecture boundaries, and includes allowlisted native evidence with original failures preserved. It will use a dedicated feature branch and reviewable pull request. `.local`, CLI credential stores, databases, backups, private logs and raw diagnostics are excluded. No merge is proposed.

The scoped native API matrix is complete across the recorded stages. Final local regression, source/evidence fingerprints and the private-file exclusion scan are rerun for the publication candidate. GitHub publication still requires separate owner approval; hosted CI cannot run for these unpublished changes until publication is authorized. No merge is proposed.
