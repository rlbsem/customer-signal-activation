"""Open the existing seller UI with bounded native Salesforce delivery."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

import uvicorn

from signals.fixtures import AS_OF
from signals.salesforce_acceptance import ObservedClient, preflight
from signals.salesforce_contract import MappingBook, OrganizationApproval
from signals.salesforce_delivery import SalesforceInbox, native_client
from signals.salesforce_dispatch import SalesforceDispatcher
from signals.seller import Model, Workbench
from signals.seller_api import app
from signals.seller_fixtures import seed_workbench
from signals.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8542)
    parser.add_argument("--model-url")
    parser.add_argument("--model", default="qwen3-14b")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    approval = OrganizationApproval(**config["approval"])
    model = None
    if args.model_url:
        parsed = urlsplit(args.model_url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.username:
            parser.error("only a separately started local inference server is supported")
        model = Model(args.model_url, args.model)
    args.workspace.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        clients = [ObservedClient(stack.enter_context(native_client(config["instance_url"], os.environ[v])),
                                  read_only=v == "SF_ADMIN_TOKEN")
                   for v in ("SF_INTEGRATION_TOKEN", "SF_REVIEWER_TOKEN", "SF_ADMIN_TOKEN")]
        inbox = SalesforceInbox(clients[0], approval, MappingBook(config["mappings"]))
        preflight(inbox, clients[1], config["integration_user_id"], config["reviewer_user_id"], admin=clients[2])
        # No acceptance request cap on the interactive operator session; one dispatch still has a bounded budget.
        inbox.client = clients[0].client
        bench = Workbench(Store(args.workspace / "workbench.sqlite"), model, AS_OF)
        seed_workbench(bench)
        worker = SalesforceDispatcher(bench, inbox, args.workspace / "delivery.sqlite")
        token = secrets.token_urlsafe(24)
        print(f"Local UI: http://127.0.0.1:{args.port}; local operator token: {token}", flush=True)
        print("Synthetic scenario clock 2026-03-31. Salesforce review records only. No messages are sent.", flush=True)
        uvicorn.run(app(bench, token, None, None, dispatcher=worker), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
