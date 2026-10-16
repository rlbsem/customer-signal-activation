"""Owner-run Metadata API deployment with a pinned non-production environment gate."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from signals.salesforce_contract import OrganizationApproval

ROOT = Path(__file__).resolve().parents[1]


def sf_json(arguments, cwd=ROOT):
    executable = shutil.which("sf")
    if not executable:
        raise RuntimeError("Install the official Salesforce CLI first")
    result = subprocess.run([executable, *arguments, "--json"], cwd=cwd,
                            capture_output=True, text=True, encoding="utf-8", timeout=900)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError("CLI response unavailable; inspect CLI locally") from None
    if result.returncode or data.get("status") != 0:
        raise RuntimeError("Salesforce CLI command failed; inspect privately")
    return data["result"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--admin-alias", required=True)
    parser.add_argument("--deploy-approved-synthetic-metadata", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.@+-]+", args.admin_alias):
        parser.error("simple local Salesforce CLI alias required")
    approval = OrganizationApproval(**json.loads(Path(args.config).read_text(encoding="utf-8"))["approval"])
    org = sf_json(["data", "query", "--target-org", args.admin_alias, "--query",
                   "SELECT Id, IsSandbox, OrganizationType FROM Organization"])
    if org.get("totalSize") != 1 or len(org.get("records", [])) != 1:
        raise RuntimeError("One verified organization required")
    approval.verify(org["records"][0])
    existing = sf_json(["data", "query", "--target-org", args.admin_alias, "--use-tooling-api", "--query",
                       "SELECT QualifiedApiName FROM EntityDefinition WHERE QualifiedApiName IN "
                       "('Seller_Action__c','Synthetic_Account__c')"])
    if existing.get("records"):
        raise RuntimeError("Object-name conflict: inspect existing metadata before any update")
    command = ["project", "deploy", "start", "--source-dir", "force-app", "--target-org", args.admin_alias, "--wait", "10"]
    checked = sf_json([*command, "--dry-run"], ROOT / "salesforce")
    if checked.get("success") is not True:
        raise RuntimeError("Metadata check-only validation did not pass")
    if args.deploy_approved_synthetic_metadata:
        deployed = sf_json(command, ROOT / "salesforce")
        if deployed.get("success") is not True:
            raise RuntimeError("Metadata deployment did not pass")
    print(json.dumps({"environment": approval.environment, "metadata_check_only": "passed",
                      "deployment": "passed" if args.deploy_approved_synthetic_metadata else "not_requested"}))


if __name__ == "__main__":
    main()
