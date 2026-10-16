# Isolated Developer Edition handoff

The isolated org, metadata, three identities and CLI authentication are already configured for the current demonstration. **Do not repeat setup or change permissions.** Use the existing aliases through `scripts/run_salesforce_acceptance.py`; its preflight mode is read-only. The [finishing review](salesforce-finish-review.md) records the approved completed experiments. Further live writes still require explicit approval. The one-time instructions below remain for a fresh, separately approved reproduction.

## Minimum handoff to continue assisted setup

1. Create a free [Salesforce Developer Edition org](https://developer.salesforce.com/signup). Use a dedicated demonstration org with no client data or paid add-ons. Keep the administrator account private.
2. Install the official [Salesforce CLI](https://developer.salesforce.com/tools/salesforcecli), then authenticate locally using `sf org login web --alias csa-demo-owner --instance-url https://login.salesforce.com`. Confirm the browser is signing into the new isolated org. Passwords and MFA stay in Salesforce's browser flow.
3. Give the assisting engineer only the local CLI alias `csa-demo-owner` and explicit approval for that org ID to host these synthetic metadata/records. Do not paste passwords, access/refresh tokens, auth URLs or CLI credential files into chat. The alias is enough to continue supported local setup. Native acceptance will subsequently require two restricted test-user logins; an administrator token must never stand in for either.

An alias is a local credential reference, not proof of environment. The setup helper queries Organization and verifies the approved ID/type before deployment. For Developer Edition, the required response is exactly `OrganizationType='Developer Edition'` and `IsSandbox=false`. For sandbox approval, use `environment='sandbox'`, the actual exact edition and `IsSandbox=true`. Never classify the org by login host alone; Developer Edition uses the same login host as production.

## Complete setup procedure (can be assisted after owner login)

Run from the repository root using Python 3.12 and the repository's existing dependencies. Set `PYTHONPATH=src` if necessary. Commands below describe fresh reproduction. The current org setup already exists and must not be repeated; the finishing review records which acceptance commands actually executed.

1. Query the org privately:

```text
sf data query --target-org csa-demo-owner --query "SELECT Id, IsSandbox, OrganizationType FROM Organization" --json
```

Copy [runtime.example.json](../salesforce/runtime.example.json) to `.local/runtime.json`. Replace its org ID/instance URL and verify them against the authenticated org. Set the explicit approval fields only for this isolated org. The example IDs are placeholders and `approved=false` deliberately blocks execution. Initial deployment only needs the approval section; complete mapping/user fields later.

2. Check metadata, then deploy through the gated helper:

```text
python scripts/deploy_salesforce_demo.py --config .local/runtime.json --admin-alias csa-demo-owner
python scripts/deploy_salesforce_demo.py --config .local/runtime.json --admin-alias csa-demo-owner --deploy-approved-synthetic-metadata
```

The first command performs check-only deployment; the second repeats the check before deployment. Both refuse production/mismatched orgs and object-name conflicts. If objects already exist, stop and inspect; the helper intentionally will not overwrite them. No Apex test level override, ignore-errors flag, permission elevation or subscription purchase is needed. Preserve actual deployment results privately. An actual validation failure must be corrected and rechecked, not relabelled passed.

3. In Setup > Users, create two test identities using available compatible licenses and minimum-access profiles: **CSA Integration** and **CSA Reviewer**. Keep the owner administrator separate. Inspect the org's existing free license allocation first; if there are insufficient compatible seats/API entitlement, stop and report that precise access constraint rather than purchasing licenses or weakening identity separation. A compatible Platform license may suffice for custom objects, depending on the actual org allocation.

Assign `Seller_Review_Integration` only to Integration, and `Seller_Review_Reviewer` only to Reviewer. Do not use System Administrator, broad Standard User grants, View All Data, Modify All Data or other permission sets granting unrelated object writes. Permission sets cannot revoke profile grants. In Object Manager > Seller Review > Page Layouts > Page Layout Assignment, assign **Synthetic Seller Review** to the test profiles. The custom review tab is enabled by both permission sets. Confirm both identities can log in and use the REST API.

4. As administrator, create exactly one synthetic registry row. Substitute the Reviewer's actual 18-character User ID:

```text
sf data create record --target-org csa-demo-owner --sobject Synthetic_Account__c --values "Name='Synthetic Cedar 0012' Account_Key__c='cedar:account-0012' Brand__c='cedar' Approved_Owner__c='REPLACE_REVIEWER_USER_ID' Active__c=true Synthetic__c=true" --json
```

Use the returned registry ID in private config. Pin Integration/Reviewer User IDs separately; set the mapping's user ID to the approved reviewer. These are synthetic account registry references, never real Account IDs. Retain a private copy of each config version when changing mappings.

5. Authenticate each restricted identity through browser OAuth:

```text
sf org login web --alias csa-demo-integration --instance-url https://login.salesforce.com
sf org login web --alias csa-demo-reviewer --instance-url https://login.salesforce.com
```

Sign into the correct test user each time. Capture tokens directly into the current PowerShell process without printing them:

```powershell
$integrationAuth = sf org auth show-access-token --target-org csa-demo-integration --json | ConvertFrom-Json
$reviewerAuth = sf org auth show-access-token --target-org csa-demo-reviewer --json | ConvertFrom-Json
$administratorAuth = sf org auth show-access-token --target-org csa-demo-owner --json | ConvertFrom-Json
if ($integrationAuth.status -ne 0 -or $reviewerAuth.status -ne 0 -or $administratorAuth.status -ne 0) { throw 'Local authentication failed' }
$env:SF_INTEGRATION_TOKEN = $integrationAuth.result.accessToken
$env:SF_REVIEWER_TOKEN = $reviewerAuth.result.accessToken
$env:SF_ADMIN_TOKEN = $administratorAuth.result.accessToken
```

Prefer the wrapper, which captures these credentials in memory and restores the prior process environment. Modern `org display` output is redacted and is not a token source. Do not print the variables. The administrator token is used only for GET environment/global-visibility checks, never as the integration or reviewer identity and never for business writes. CLI manages its own refresh credentials; no username/password grant or embedded client secret is used.

## Execute acceptance

```text
python -m signals.salesforce_acceptance preflight --config .local/runtime.json --output .local/preflight-001
python -m signals.salesforce_acceptance acceptance --config .local/runtime.json --output .local/acceptance-001 --run-id acceptance-001 --execute-approved-synthetic-writes
```

Use a new output directory and run ID for each run and obtain owner approval before live writes. Preflight reads only. Acceptance creates a small synthetic review workload and attempts denied mutations of those demo records. Explicit permission tests require specific denials; the reviewer-create contract independently verifies no-Create rights and no effect while retaining the observed generic rejection if returned. An arbitrary error never passes. Unexpected rights/effects stop the run; do not automatically change permissions or clean up records. No real Account writes are required.

For the operator UI after acceptance, reopen the acceptance workspace to inspect its saved, clearly labelled handwritten proposal:

```text
python scripts/salesforce_workbench.py --config .local/runtime.json --workspace .local/acceptance-001/private-runtime
```

The launcher prints a temporary **local UI** login token, binds to 127.0.0.1 and performs native preflight. Salesforce tokens remain server-side. To generate new genuine model output, add the existing separately started local model endpoint, for example `--model-url http://127.0.0.1:8093/v1 --model qwen3-14b`. With no model endpoint, generation is unavailable; saved acceptance content is explicitly labelled as a software fixture. Scenario time remains March 31, 2026; execution timestamps are actual UTC times.

Review the draft/source support, approve exact content, then deliver. Retry clicks respect the persisted schedule/budget. Blocked/exhausted work offers **Reconcile existing record only**, which never creates a new record. In Salesforce, open the Seller Reviews tab and Synthetic Seller Reviews list, then inspect the exact content and mark Reviewed/Rejected with internal notes. This status does not send anything or synchronize Workbench rejection.

For explicit read-only CLI recovery:

```text
python -m signals.salesforce_acceptance reconcile --config .local/runtime.json --output .local/reconciliation-001 --workbench .local/acceptance-001/private-runtime/workbench.sqlite --journal .local/acceptance-001/private-runtime/delivery.sqlite --action-key REPLACE_APPROVED_ACTION_HASH
```

On completion, remove token variables from the session. Keep private runtime and CLI credentials local. Use the [evidence procedure](salesforce-evidence.md) before sharing results. No GitHub publication is authorized.
