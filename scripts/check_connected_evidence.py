"""Check published native records offline; this invocation does not execute native acceptance."""
import json
from pathlib import Path

from signals.integration_evidence import validate

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    print(json.dumps(validate(ROOT / 'docs/evidence/connected-integration/native', root=ROOT)))
