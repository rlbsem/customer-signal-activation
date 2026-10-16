# Reviewer-create correction: local verification

This record is local Python/HTTP/Chromium/dbt execution, not native Salesforce business-write acceptance. Prior verification files and recorded inference results remain unchanged.

[Executed verification](verification.json) · [Complete regression cases](tests.xml) · [Browser contract screenshot](contract-review.png) · [Native execution status](../../salesforce-native/README.md)

The suite covers strict permission rejections and the generic entity rejection combined with independent no-Create rights and unchanged global record IDs. Adversarial cases include unexpected successful creation, missing global visibility, wrong environment/identity, stale keys, unrelated errors and administrator write attempts. The existing failure-recovery, process-death, browser and dbt tests also execute. Export tests check that private fields and credentials cannot enter native evidence; package tests exclude runtime, keys and backups.

Two independent commercial demonstrations must match, archived model summaries are independently recomputed and original evidence hashes are checked. The native preflight/failed attempt are separate records; full native acceptance remains incomplete until the approved live matrix executes.

[Preservation baseline](existing-evidence-sha256.json) and [baseline provenance](baseline-provenance.json) capture the existing folder at the start of this review. One pre-existing image, `docs/images/browser-proof.png`, differed from the earlier upstream archive hash before any edits. Its initial and current hashes agree. The image is preserved, the old upstream baseline is retained, and the discrepancy is disclosed rather than silently treating the files as upstream-identical.
