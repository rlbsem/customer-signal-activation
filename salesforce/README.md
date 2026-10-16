# Synthetic seller-review metadata

This Salesforce DX source-format package targets REST/Metadata API 65.0. The owner has deployed it in the isolated Developer Edition org. Native preflight and read-only inspection confirm the deployed schema/effective roles and three active validation rules. The scoped native delivery/security matrix completed across recorded stages; see the [execution record](../docs/evidence/salesforce-native/README.md). The finishing review has not redeployed or changed this metadata.

- `Synthetic_Account__c`: synthetic registry keyed by brand/local account, active/synthetic flags and approved User lookup. The integration/reviewer can only read this registry; the owner seeds it.
- `Seller_Action__c`: unique external action key, exact canonical approved payload, hashes, pinned registry/User references, readable subject/draft/action/notice, review status and internal notes.
- `Seller_Review_Integration`: Create/Read review records, Read registry, API access; no object update/delete or unrelated business writes.
- `Seller_Review_Reviewer`: Read/Edit review status/notes; no Create/Delete, no editing approved payload or mapping fields.
- Three validation rules: synthetic mapping eligibility at insert, required review content at insert, and immutable approved content on update. Field definitions are not universally required, allowing scoped reviewer field security; the validation rule enforces insert requirements.
- Review tab, list view and one-column record layout. The owner assigns the layout to the restricted profiles. No custom app, Apex, Flow, trigger, email or standard Task automation is installed.

Permission sets are additive. Minimum-access profiles, sharing and actual effective permissions must be tested in the native org. Review sharing is Public Read/Write within this isolated synthetic org so a reviewer can update integration-owned records under FLS; registry sharing is Public Read Only. No production deployment suitability is implied.

[Runtime example](runtime.example.json) contains placeholders and no credentials. Copy it into ignored `.local/` and complete it privately. The strict preflight checks the authenticated Organization ID, IsSandbox and exact OrganizationType against explicit approval. It accepts an approved sandbox or ordinary Developer Edition; it rejects ordinary production editions.
