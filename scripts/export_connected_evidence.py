"""Export an allowlisted derivative, preserving the private source record hash."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from signals.contracts import digest
from signals.integration_evidence import validate

ROOT = Path(__file__).resolve().parents[1]


def sanitize(raw, private_hash):
    report = {k: raw[k] for k in ('status', 'provenance', 'started_utc', 'finished_utc', 'checks',
                                 'source_sha256', 'inference', 'scope', 'continuation', 'error', 'error_type') if k in raw}
    report['private_record_sha256'] = private_hash
    report['requests'] = []
    for event in raw['requests']:
        item = {k: event[k] for k in ('method', 'resource', 'started_utc', 'status', 'fault', 'transport_outcome',
                                      'elapsed_ms', 'actor', 'error_codes', 'stage') if k in event}
        if event.get('request_id'):
            item['request_reference_sha256'] = digest(event['request_id'])
        usage = event.get('api_usage')
        if isinstance(usage, str) and re.fullmatch(r'api-usage=\d+/\d+', usage):
            item['api_usage'] = usage
        report['requests'].append(item)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--output', default='docs/evidence/connected-integration/native')
    parser.add_argument('--additional-failed-attempt', action='append', default=[])
    args = parser.parse_args()
    work, output = Path(args.workspace), ROOT / args.output
    if output.exists():
        raise ValueError('preserve_previous_public_evidence')
    record_path = work / 'verification.json'
    raw = json.loads(record_path.read_text(encoding='utf-8'))
    report = sanitize(raw, hashlib.sha256(record_path.read_bytes()).hexdigest())
    files = {'verification.json': report,
             'source-before.json': json.loads((work / 'source.json').read_text()),
             'source-after.json': json.loads((work / 'source-after.json').read_text()),
             'intent.json': json.loads((work / 'intent.json').read_text())}
    if (work / 'prior-verification.json').exists():
        files['initial-failed-attempt.json'] = sanitize(
            json.loads((work / 'prior-verification.json').read_text()),
            raw['continuation']['prior_private_record_sha256'])
    if (work / 'warehouse-feedback-failed-attempt.json').exists():
        content = (work / 'warehouse-feedback-failed-attempt.json').read_bytes()
        files['feedback-failed-attempt.json'] = dict(json.loads(content),
                                                    private_record_sha256=hashlib.sha256(content).hexdigest())
    for index, path in enumerate(args.additional_failed_attempt):
        content = Path(path).read_bytes()
        failed = json.loads(content)
        if failed.get('status') != 'FAILED':
            raise ValueError('additional_record_must_be_a_failed_attempt')
        files[f'failed-continuation-{index+1}.json'] = sanitize(failed, hashlib.sha256(content).hexdigest())
    encoded = json.dumps(files)
    forbidden = [r'https?://', r'(?<![A-Za-z0-9])00D[A-Za-z0-9]{12,15}(?![A-Za-z0-9])',
                 r'(?<![A-Za-z0-9])005[A-Za-z0-9]{12,15}(?![A-Za-z0-9])',
                 r'BEGIN .*PRIVATE KEY', r'(?i)access_token', r'[A-Z]:\\']
    if any(re.search(pattern, encoded) for pattern in forbidden):
        raise ValueError('unexpected_private_content')
    output.mkdir(parents=True)
    for name, value in files.items():
        (output / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    checked = validate(output, root=ROOT)
    (output / 'offline-check.json').write_text(json.dumps(checked, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(checked))


if __name__ == '__main__':
    main()
