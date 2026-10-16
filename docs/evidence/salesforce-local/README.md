# Executed local Salesforce-contract verification

These results come from local Python, Chromium, dbt, HTTP services and an explicitly labelled Salesforce contract emulator. **No native Salesforce execution, deployment or new LLM inference occurred.**

Reproduce with `python scripts/verify_salesforce.py` after the existing Python 3.12/dependency/Chromium setup. This dedicated verifier preserves archived evidence. The original `scripts/verify.py` regenerates the original root evidence and should not be used to reproduce this additive acceptance revision.

[Verification](verification.json) · [All regression cases](tests.xml) · [Local contract review screenshot](contract-review.png) · [Prior evidence fingerprints](original-evidence-sha256.json)

The added tests cover approved sandbox and Developer Edition environments, production/mismatched identity rejection, synthetic mapping/user eligibility, duplicate contention, lost acknowledgement, exact read-back, permission failures, bounded retries/exhaustion, journal pinning, actual child-process death, native-runner execution against local emulation, and the browser operator workflow. The complete original regression suite also runs.

Two independent source-to-cash demonstrations are compared. Existing archived inference/evidence files are checked byte-for-byte against their pinned prior hashes. No archived result is regenerated or relabelled by this verifier. Native requirements remain in the [acceptance plan](../../salesforce-acceptance-plan.md).
