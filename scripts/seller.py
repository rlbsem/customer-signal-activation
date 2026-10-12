"""Launch the on-demand seller application and its separately persisted CRM receiver."""

import argparse
import secrets
from pathlib import Path

import uvicorn

from signals.fixtures import AS_OF
from signals.harness import serve
from signals.seller import Model, Workbench, task_destination
from signals.seller_api import app
from signals.seller_fixtures import seed_workbench
from signals.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path("work/seller-demo"))
    parser.add_argument("--port", type=int, default=8530)
    parser.add_argument("--model-url", default="http://127.0.0.1:8093/v1")
    parser.add_argument("--model", default="qwen3-14b")
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=True)
    model = None if args.no_model else Model(args.model_url, args.model)
    workbench = Workbench(Store(args.workspace / "seller.sqlite"), model, AS_OF)
    seed_workbench(workbench)
    operator, destination = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    with serve(task_destination(args.workspace / "crm.sqlite", destination)) as url:
        print(f"Seller workbench: http://127.0.0.1:{args.port}", flush=True)
        print(f"Local operator login token: {operator}", flush=True)
        print("Synthetic scenario clock: 2026-03-31. No external messages are sent.", flush=True)
        uvicorn.run(app(workbench, operator, url, destination), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
