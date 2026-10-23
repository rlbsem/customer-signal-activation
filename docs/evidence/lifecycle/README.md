# Lifecycle execution evidence

The JSON, JUnit and screenshots in this directory describe only new local synthetic lifecycle execution. Existing native Salesforce, Salesforce–Snowflake and seller evidence remain historical and separate.

`baseline.json` records the prior main revision and SHA-256 of 443 protected evidence/image files. `execution.json` records actual independent local receipts, real dbt outputs, late-correction parity, fixture counts and screenshot hashes. `tests.xml` records executed lifecycle tests. Full existing-regression results are reported separately.

The screenshots come from the actual loopback operator app driven through approval, lost acknowledgment and receipt reconciliation. No model inference or external messages are part of this lane.

The final source and screenshot hashes are checked against `execution.json` and `browser.json`. The larger final-source observation replays a previously generated 1,200-person source; fresh-pair generation is separately tested. `tests.xml` records the corrected 17-test stage; `safety-tests.xml` records 17 final safety cases (two analytics/large cases deselected). These overlap and must not be added. The complete final suite contains 19 cases and is rerun in CI. `full-regression.xml` is the earlier 420-test full run. Initial pre-coverage-correction results remain explicitly qualified in `../lifecycle-initial`.
