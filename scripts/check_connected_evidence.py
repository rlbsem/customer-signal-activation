"""Check published native records offline; this invocation does not execute native acceptance."""
import argparse
import hashlib
import json
from pathlib import Path

from signals.integration_evidence import validate
from signals.evidence_sources import historical_source_tree

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-ref', help='Exact historical Git SHA; current-tree validation remains the default')
    args = parser.parse_args()
    folder = ROOT / 'docs/evidence/connected-integration/native'
    if args.source_ref:
        report = json.loads((folder / 'verification.json').read_text())
        # These two offline postprocessors were already excluded by the native
        # checker. Do not add business modules to this exemption.
        postprocessors = {'scripts/export_connected_evidence.py', 'src/signals/integration_evidence.py'}
        fingerprints = {name: value for name, value in report['source_sha256'].items() if name not in postprocessors}
        with historical_source_tree(ROOT, fingerprints, args.source_ref) as historical:
            result = validate(folder, root=historical)
        changed = [name for name, expected in fingerprints.items()
                   if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected]
        result.update(historical_source_revision=args.source_ref, current_source_differences=changed,
                      current_native_acceptance='not_executed')
    else:
        result = validate(folder, root=ROOT)
    print(json.dumps(result))
