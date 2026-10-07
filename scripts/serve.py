import argparse
import json
import os
from pathlib import Path

import uvicorn

from signals.api import app
from signals.store import Store

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True)
parser.add_argument("--port", type=int, default=8522)
args = parser.parse_args()
root = Path(args.workspace).resolve()
root.mkdir(parents=True, exist_ok=True)
store = Store(root / "signals.sqlite")
print(f"Browser: http://127.0.0.1:{args.port}/ | Database: {store.path}", flush=True)
uvicorn.run(app(store, json.loads(os.environ.get("SIGNALS_TOKENS", "{}"))), host="127.0.0.1", port=args.port)
