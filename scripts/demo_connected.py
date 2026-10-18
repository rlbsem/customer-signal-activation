"""Replay published, sanitized native snapshots through local SQL; no vendor requests."""
import argparse
import json
from pathlib import Path

from signals.integration_activation import verify_decision
from signals.integration_warehouse import LocalWarehouse

ROOT = Path(__file__).resolve().parents[1]


def replay():
    folder = ROOT / 'docs/evidence/connected-integration/native'
    snapshots = [json.loads((folder / name).read_text()) for name in ('source-before.json', 'source-after.json')]
    with LocalWarehouse() as warehouse:
        results = []
        for snapshot in snapshots:
            load = warehouse.load(**snapshot['body'])
            decisions = warehouse.decisions()
            for decision in decisions:
                verify_decision(decision, snapshot)
            results.append({'inserted': load['inserted'], 'decisions': decisions})
        old = warehouse.load(**snapshots[0]['body'])
        assert old['inserted'] == {'accounts': 0, 'reviews': 0}
        assert warehouse.decisions() == results[-1]['decisions']
    return {'provenance': 'local_sql_replay_of_recorded_sanitized_native_sources',
            'vendor_calls': 0, 'before': results[0], 'after': results[1], 'late_replay_no_regress': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='work/connected-replay.json')
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = replay()
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'vendor_calls': 0, 'before': result['before']['decisions'][0]['decision_action'],
                      'after': result['after']['decisions'][0]['decision_action'], 'late_replay_no_regress': True}))


if __name__ == '__main__':
    main()
