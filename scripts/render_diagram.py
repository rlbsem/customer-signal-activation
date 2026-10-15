"""Optional presentation check using a supplied Mermaid 10.9.3 browser bundle."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--mermaid-js", required=True, help="Path to Mermaid 10.9.3 mermaid.min.js")
args = parser.parse_args()
source = re.search(r"```mermaid\n(.*?)```", (ROOT / "README.md").read_text(encoding="utf-8"), re.S)[1]
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_content("<html><body></body></html>")
    page.add_script_tag(path=args.mermaid_js)
    svg = page.evaluate(
        """async source => {
      mermaid.initialize({startOnLoad:false,securityLevel:'strict'});
      await mermaid.parse(source);
      return (await mermaid.render('architecture',source)).svg;
    }""",
        source,
    )
    browser.close()
# Explicit dark canvas: the exported evidence SVG must remain readable when
# viewed as a standalone asset on a light GitHub background.
svg_start = svg.find(">")
if svg_start < 0:
    raise RuntimeError("Mermaid renderer returned invalid SVG")
viewbox_match = re.search(r'viewBox="([^"]+)"', svg[: svg_start + 1])
if viewbox_match is None:
    raise RuntimeError("Mermaid SVG is missing a viewBox")
viewbox_parts = viewbox_match.group(1).split()
if len(viewbox_parts) != 4:
    raise RuntimeError("Mermaid SVG has an invalid viewBox")
x, y, width, height = viewbox_parts
background = f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#10101D"/>'
svg = svg[: svg_start + 1] + background + svg[svg_start + 1 :]
target = ROOT / "docs/evidence/architecture.svg"
target.write_text(svg, encoding="utf-8")
record = {
    "status": "parsed_and_rendered",
    "renderer": "Mermaid supplied browser bundle",
    "bundle_sha256": hashlib.sha256(Path(args.mermaid_js).read_bytes()).hexdigest(),
    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    "svg_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
}
(ROOT / "docs/evidence/diagram-check.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps(record))
