"""Trusted local-host administration of synthetic operational authority; no vendor calls."""
import argparse
import json
from pathlib import Path

from signals.seller import Workbench
from signals.fixtures import AS_OF
from signals.store import Store

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--workspace", type=Path, required=True, help="Existing seller demo workspace")
parser.add_argument("--issuer", choices=["support_operations", "commercial_operations"], required=True)
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--grant", type=Path, help="Reviewed synthetic authority JSON")
group.add_argument("--revoke", help="Previously registered authority ID")
args = parser.parse_args()
assert (args.workspace / "seller.sqlite").is_file(), "Existing demo workspace required"
bench = Workbench(Store(args.workspace / "seller.sqlite"), None, AS_OF)
if args.grant:
    value = bench.grant_authority(json.loads(args.grant.read_text()), issuer=args.issuer)
    print(json.dumps({"registered": value["id"], "scope": "synthetic local demo"}))
else:
    bench.revoke_authority(args.revoke, issuer=args.issuer)
    print(json.dumps({"revoked": args.revoke, "scope": "synthetic local demo"}))
