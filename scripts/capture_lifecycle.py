"""Independent current-UI capture; preserves the separately executed analytics record."""

import hashlib
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from signals.harness import serve
from signals.lifecycle_api import app
from signals.lifecycle_destination import app as destination

w = Path(sys.argv[1])
w.mkdir(parents=True, exist_ok=False)
out = Path(sys.argv[2])
with (
    serve(destination(w / "destination.sqlite")) as remote,
    serve(app(w / "core.sqlite", remote, "local-capture")) as url,
    sync_playwright() as pw,
):
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    page.goto(url)
    page.locator(".action").first.wait_for()
    page.locator("#token").fill("local-capture")
    card = page.locator(".action").filter(
        has=page.get_by_role("heading", name="Quiet-trial assistance", exact=True)
    )
    for label, op in [
        ("Approve exact action", "approve"),
        ("Lose acknowledgment", "lose_ack"),
        ("Reconcile receipt", "reconcile"),
    ]:
        card.get_by_role("button", name=label).click()
        page.wait_for_function(f"document.querySelector('#notice').textContent.includes('{op} result')")
    assert card.locator(".badge").inner_text().startswith("accepted")
    for name, width, height in [("desktop", 1440, 1100), ("mobile", 390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        page.evaluate("window.scrollTo(0,0)")
        assert page.locator("body").evaluate("(e)=>e.scrollWidth<=innerWidth")
        page.screenshot(path=str(out / f"lifecycle-{name}.png"), full_page=True)
    data = {
        "scope": "Fresh local UI capture; no model or vendor execution",
        "browser": browser.version,
        "viewports": [[1440, 1100], [390, 844]],
        "source_sha256": {
            "web/lifecycle.html": hashlib.sha256(Path("web/lifecycle.html").read_bytes()).hexdigest()
        },
        "screenshots": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob("*.png")},
        "flow": ["exact approval", "lost acknowledgment", "independent receipt reconciliation"],
        "accepted": 1,
        "layout_overflow": False,
    }
    (out / "browser.json").write_text(json.dumps(data, indent=2), encoding="utf8")
    browser.close()
print("Current desktop/mobile UI capture passed")
