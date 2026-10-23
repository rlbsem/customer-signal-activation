import argparse
import secrets
from pathlib import Path
import uvicorn
from signals.harness import serve
from signals.lifecycle_destination import app as destination
from signals.lifecycle_api import app

p = argparse.ArgumentParser()
p.add_argument("--workspace", default=".local/lifecycle")
p.add_argument("--port", type=int, default=8570)
args = p.parse_args()
w = Path(args.workspace)
w.mkdir(parents=True, exist_ok=True)
token = secrets.token_urlsafe(24)
print("Local lifecycle operator token: " + token, flush=True)
with serve(destination(w / "destination.sqlite")) as url:
    uvicorn.run(app(w / "core.sqlite", url, token), host="127.0.0.1", port=args.port, log_level="warning")
