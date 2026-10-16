"""Export explicitly selected native records; no config, logs or database copying."""
import argparse
import json
from pathlib import Path
import re

from signals.salesforce_evidence import export_record

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    for name in args.input:
        source = Path(name)
        label = source.parent.name
        if not re.fullmatch(r"[A-Za-z0-9_-]+", label):
            raise ValueError("simple evidence-directory label required")
        target = output / (label + ".json")
        if target.exists():
            raise ValueError("evidence label collision")
        data = export_record(source, ROOT)
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"file": target.name, "status": data["status"], "requests": len(data["requests"]),
                          "source_fingerprint_matches_current": data["source_fingerprint_matches_current"]}))


if __name__ == "__main__":
    main()
