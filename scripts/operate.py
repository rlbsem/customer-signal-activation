import argparse
import json

from signals.analytics import build
from signals.contracts import timestamp
from signals.decision import plan
from signals.finance import plan_conversions
from signals.reconcile import reconcile
from signals.store import Store
from signals.worker import deliver_one

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["plan", "conversions", "deliver", "reconcile", "build", "status"])
parser.add_argument("--database", required=True)
parser.add_argument("--as-of", help="Explicit UTC review/dispatch timestamp")
parser.add_argument("--remote", help="Loopback synthetic destination URL")
parser.add_argument("--workspace", help="New dbt candidate directory")
args = parser.parse_args()
store = Store(args.database)
if args.action in ("plan", "conversions", "deliver", "build") and not args.as_of:
    parser.error("--as-of is required")
if args.action in ("deliver", "reconcile") and not args.remote:
    parser.error("--remote is required")
if args.action == "build" and not args.workspace:
    parser.error("--workspace is required")
clock = timestamp(args.as_of) if args.as_of else None
if args.action == "plan":
    result = plan(store, clock)
elif args.action == "conversions":
    result = plan_conversions(store, clock)
elif args.action == "deliver":
    while deliver_one(store, args.remote, clock):
        pass
    result = store.status()
elif args.action == "reconcile":
    result = reconcile(store, args.remote)
elif args.action == "build":
    result = build(store, clock, args.workspace)
else:
    result = store.status()
print(json.dumps(result, indent=2))
