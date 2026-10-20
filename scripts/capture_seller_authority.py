"""Capture the actual local review workflow; unchanged archived inference, no vendor calls."""
import argparse
import hashlib
import json
import secrets
from pathlib import Path

from playwright.sync_api import sync_playwright

from signals.fixtures import AS_OF
from signals.harness import serve
from signals.seller import Workbench, task_destination
from signals.seller_api import app
from signals.seller_fixtures import seed_workbench
from signals.store import Store
from verify_seller_authority import Replay, ROOT, TRACE

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.workspace.mkdir(parents=True, exist_ok=False)
args.output.mkdir(parents=True, exist_ok=True)
original = json.loads((ROOT / TRACE).read_text())
bench = Workbench(Store(args.workspace / "control.sqlite"), Replay(original["raw_proposal"]), AS_OF)
seed_workbench(bench)
for doc in original["input_snapshot"]["documents"]:
    if doc["kind"] in ("inquiry", "call_note", "account_document"):
        bench.document(dict(id=doc["id"], title=doc["title"], text=doc["text"], kind=doc["kind"],
                            brand="cedar", account="account-0000", revision=1, occurred_at="2026-03-30T12:00:00Z"))
bench.generate("cedar", "account-0000")
operator, destination = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
errors, pictures = [], {}
with serve(task_destination(args.workspace / "receiver.sqlite", destination)) as receiver:
    with serve(app(bench, operator, receiver, destination)) as url, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        page.locator("#token").fill(operator)
        page.get_by_role("button", name="Open workbench").click()
        page.get_by_role("button", name="Customer incident").click()
        page.locator("#draft").wait_for()
        assert page.locator("#draft").input_value() == original["raw_proposal"]["draft"]
        assert page.locator("#approve").is_disabled()
        for name in ("advisory", "governed"):
            if name == "governed":
                page.get_by_role("button", name="Prepare governed review").click()
                page.get_by_text("Governed content prepared", exact=False).wait_for()
                assert page.locator("#draft").input_value() != original["raw_proposal"]["draft"]
                page.get_by_role("button", name="Approve CRM task", exact=True).click()
                page.get_by_role("button", name="Deliver approved task", exact=True).click()
                page.locator(".receipt").wait_for()
                assert page.locator("#draft").is_disabled()
            page.evaluate("scrollTo(0,0)")
            target = args.output / (name + ".png")
            page.screenshot(path=target, full_page=True)
            pictures[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator(".receipt").is_visible()
        assert not errors
        browser.close()
record = {"scope": "Actual Chromium against local synthetic services; archived draft replay; no fresh inference or vendor execution",
          "archived_trace": TRACE, "archived_trace_sha256": hashlib.sha256((ROOT / TRACE).read_bytes()).hexdigest(),
          "screenshots": pictures, "mobile_overflow": False, "page_errors": errors,
          "receipt": json.loads(bench.overview()["actions"][0]["receipt"])}
(args.output / "browser.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"screenshots": pictures, "page_errors": errors}))
