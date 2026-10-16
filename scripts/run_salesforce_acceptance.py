"""Use existing Salesforce CLI identities without printing or persisting their tokens."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from signals.salesforce_acceptance import main as accept
from signals.salesforce_contract import DeliveryError


def access_token(executable, alias):
    if not re.fullmatch(r"[A-Za-z0-9_.@+-]+", alias):
        raise DeliveryError("invalid_local_cli_alias")
    result = subprocess.run([executable, "org", "auth", "show-access-token", "--target-org", alias, "--json"],
                            capture_output=True, text=True, encoding="utf-8", timeout=90,
                            env=dict(os.environ, SF_DISABLE_TELEMETRY="true", SF_AUTOUPDATE_DISABLE="true"))
    try:
        data = json.loads(result.stdout)
        token = data["result"]["accessToken"]
        if (result.returncode or data.get("status") != 0 or not isinstance(token, str)
                or not token or any(c.isspace() for c in token)):
            raise ValueError
        return token
    except (ValueError, KeyError, TypeError):
        raise DeliveryError("existing_cli_authentication_unavailable") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "acceptance"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--resume-from")
    parser.add_argument("--integration-alias", default="csa-demo-integration")
    parser.add_argument("--reviewer-alias", default="csa-demo-reviewer")
    parser.add_argument("--administrator-alias", default="csa-demo-owner")
    parser.add_argument("--sf-executable")
    parser.add_argument("--execute-approved-synthetic-writes", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "acceptance" and (not args.run_id or not args.execute_approved_synthetic_writes):
        parser.error("acceptance requires a fresh run ID and explicit approval for the synthetic write experiments")
    executable = args.sf_executable or shutil.which("sf")
    if not executable:
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "sf/bin/sf.cmd"
        executable = str(candidate) if candidate.exists() else None
    if not executable:
        raise DeliveryError("salesforce_cli_not_found")
    roles = {"SF_INTEGRATION_TOKEN": args.integration_alias, "SF_REVIEWER_TOKEN": args.reviewer_alias,
             "SF_ADMIN_TOKEN": args.administrator_alias}
    original = {name: os.environ.get(name) for name in roles}
    try:
        for name, alias in roles.items():
            os.environ[name] = access_token(executable, alias)
        command = [args.mode, "--config", args.config, "--output", args.output]
        if args.run_id:
            command.extend(["--run-id", args.run_id])
        if args.resume_from:
            command.extend(["--resume-from", args.resume_from])
        if args.execute_approved_synthetic_writes:
            command.append("--execute-approved-synthetic-writes")
        return accept(command)
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
