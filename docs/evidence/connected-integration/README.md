# Connected Salesforce ↔ Snowflake execution

**Completed against both actual systems across recorded stages.** The existing pinned Salesforce Developer Edition and monitored Snowflake fixture warehouse were reused. One new immutable synthetic review was created, its real success acknowledgement was discarded by the client, the exact effect was recovered, and actual CRM feedback changed the warehouse recommendation from `clarify_need` to `hold`.

This is an internal review workflow. It does not demonstrate customer contact, a sale, business uplift, fresh LLM inference or production deployment.

## Executed result

| Observation | Actual result |
|---|---|
| Source before | One active synthetic account; two Reviewed historical reviews; zero Pending |
| Initial Snowflake decision | One `clarify_need` internal review recommendation |
| Salesforce effect | Exactly one create, HTTP 201; client-controlled acknowledgement loss |
| Recovery | Persisted dispatcher reopened; exact receipt recovered; repeated dispatch adds no POST |
| Independent reader | Separate reviewer compared all immutable destination fields to the approved intent |
| Independent key cardinality | One record with the action key, observed through the reviewer's explicit custom-field permissions |
| Source conservation | Pinned account and both old reviews unchanged; exactly one Pending review added |
| Feedback Snowflake decision | Three reviews: two Reviewed, one Pending; decision `hold` |
| Warehouse replay | Repeated delivery inserts zero rows; older actual batch cannot regress the decision |
| Cross-engine comparison | Exact Snowflake/DuckDB SQL results and independent Python source oracle agree |
| Full comparison | Feedback built from appended versions matches an independent complete snapshot on DuckDB |
| Restricted reader | Separate Snowflake consumer reads candidate view; three raw-table reads denied in each lane |
| Cleanup | Both owned transient schemas dropped; final metadata-only postflight observed SUSPENDED and zero integration schemas |

[Final composite verification](native/verification.json) · [Approved intent](native/intent.json) · [Source before](native/source-before.json) · [Source after](native/source-after.json) · [Offline record check](native/offline-check.json).

## Preserved execution stages

| Stage | Recorded outcome |
|---|---|
| [Initial attempt](native/initial-failed-attempt.json) | **FAILED**, 26 Salesforce requests. Initial Snowflake lane passed with 53 statements; one Salesforce create, lost-ack recovery and independent exact read-back passed. Administrator custom-field COUNT returned `INVALID_FIELD`. |
| [First read-only continuation](native/failed-continuation-1.json) | **FAILED**, 16 additional GETs. Reviewer count and source conservation passed; feedback SQL and consumer checks passed. Immediate warehouse suspension confirmation failed. |
| [Feedback attempt](native/feedback-failed-attempt.json) | **FAILED** at cleanup confirmation after 69 Snowflake statements. All analytical, replay, source-readback and consumer checks passed; schema drop and suspend commands succeeded, but immediate metadata did not establish SUSPENDED. This failure is retained. |
| [Second read-only continuation](native/failed-continuation-2.json) | **FAILED**, 16 additional GETs. The isolated native Python environment lacked a module pulled in by the new postflight helper; no native postflight query or new Salesforce write occurred. The helper was corrected and locally tested. |
| [Final read-only continuation](native/verification.json) | **PASSED** across linked stages. 16 additional GETs and four metadata-only Snowflake statements confirmed the saved effect, final warehouse state and absent schemas. No further create, metadata deployment or permission change. |

The final composite contains 42 Salesforce observations: the 26-request initial stage plus the 16-request final continuation. The two intervening 16-request failures are separately retained, for 74 Salesforce requests across the four execution attempts. Earlier standalone read-only discovery/preflight is not included in that count. Do not sum composite reports as if inherited observations were new requests.

The administrator's broad record visibility did not imply custom-field FLS. The corrected count uses the independently authenticated reviewer, whose explicit field permissions already existed. No user or permission was changed to obtain a pass. The exact cause of the immediate suspension-observation mismatch is not established; the subsequent direct observation is the final state evidence.

Each derivative retains its private source-record SHA-256. Native IDs, instance/account names, URLs, credentials and raw messages are excluded. Request references are hashed. Business/source fingerprints from the inherited attempt retain their original version; continuation compatibility verifies unchanged business modules. The two offline evidence-processing modules are verified by local/CI tests separately from the native executable fingerprints.

## Resource observations

There are **126 distinct Snowflake query IDs**: 53 initial-lane statements, 69 feedback-lane statements and four final metadata checks. Six of the 122 lane statements are expected denied consumer reads, with provider code 2003. The builder separately established the objects and candidate view before those tests.

The initial builder-session collector observed 35 completed successful statements, 33,280 scanned bytes and 9,095 summed query milliseconds. The feedback collector observed 51 completed successful statements, 60,416 scanned bytes and 10,344 summed query milliseconds. Reported cloud-service attribution was 0.001291 and 0.001396 credits respectively. These are partial session observations before cleanup, not total elapsed time, warehouse compute credits or final billed charges. Uncompleted collector rows and other sessions are excluded; unavailable per-query measurements remain null.

Both lanes observed X-Small, 60-second auto-suspend, one cluster and disabled query acceleration. The restricted role could not see the attached resource monitor. Its one-credit, NEVER-reset configuration relies on the owner's previously verified setup; the runner did not increase it. No new warehouse, billing attachment or paid service was provisioned. The final suspended state is an actual postflight observation.

## Evidence boundaries

| Layer | Verification |
|---|---|
| Local contract/fault tests | Schema/identity conflict, stale state, owner/permission boundaries, rate limits and exhaustion, absent uncertain receipts, forged SQL results, exact payload tampering and real local child-process death |
| Native connected acceptance | Actual Salesforce extraction → Snowflake source ingestion/SQL → one approved immutable Salesforce review → independent read-back → Snowflake feedback |
| Prior native Salesforce matrix | [Existing staged CRUD/FLS and mutation checks](../salesforce-native/README.md), preserved separately |
| Prior Snowflake/dbt acceptance | [Revenue Metrics Platform fixture evidence](https://github.com/rlbsem/revenue-metrics-platform/blob/main/docs/evidence/snowflake/fixture/README.md), preserved in its original repository |
| Hosted CI | Executes local regression, replay and offline evidence validation without native credentials; native calls are not run in CI |
| Unexecuted scope | Native process kill, induced native API rate limit, multi-worker cloud contention, atomic cross-record Salesforce serialization, production CDC/throughput and customer outcomes |

[Architecture and operator procedure](../../connected-integration.md) · [Source-to-result checker](../../../src/signals/integration_evidence.py).

[Local verification](local/verification.json): 352 tests passed with zero failures, errors or skips; two independent full demos matched, 360 archived inference traces validated and 385 earlier evidence files preserved. [Test cases](local/tests.xml). [GitHub verification runs](https://github.com/rlbsem/customer-signal-activation/actions?query=branch%3Afeat%2Fsalesforce-snowflake-roundtrip) independently run the full suite, replay and offline evidence check. Follow the individual run's result for hosted status.
