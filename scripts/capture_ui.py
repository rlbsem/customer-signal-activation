"""Capture real local pages using preserved inference; never contacts Salesforce or a model."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3

from playwright.sync_api import sync_playwright

from signals.api import app as intake_app
from signals.contracts import canonical
from signals.fixtures import AS_OF
from signals.harness import serve
from signals.seller import Workbench, task_destination
from signals.seller_api import app as seller_app
from signals.seller_fixtures import seed_workbench
from signals.store import Store

ROOT = Path(__file__).resolve().parents[1]


def capture(workspace, output):
    workspace, output = Path(workspace), Path(output)
    workspace.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=True)
    intake = Store(workspace / "capture-intake.sqlite")
    bench = Workbench(Store(workspace / "capture-seller.sqlite"), None, AS_OF)
    seed_workbench(bench)
    source = ROOT / "docs/evidence/seller/application.json"
    saved = json.loads(source.read_text(encoding="utf-8"))
    record = next(r for r in saved["runs"] if r["snapshot"]["account"] == "account-0012")
    old_action = next(a for a in saved["actions"] if a["run_id"] == record["id"])
    reviewed = json.loads(old_action["payload"]) if isinstance(old_action["payload"], str) else old_action["payload"]
    if record["configuration"]["mode"] != "live" or record["status"] != "review_required":
        raise RuntimeError("Executed recorded proposal required")
    with bench.store.tx() as c:
        bench.current(c, record)
        c.execute("INSERT INTO seller_runs VALUES(?,?,?,?)",
                  (record["id"], record["snapshot"]["brand"], record["snapshot"]["account"], canonical(record)))
    operator, destination = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    errors = []
    with serve(intake_app(intake, {})) as intake_url, serve(task_destination(workspace / "capture-crm.sqlite", destination)) as crm_url:
        with serve(seller_app(bench, operator, crm_url, destination)) as seller_url, sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 960}, device_scale_factor=1)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.clock.install(time=datetime(2026, 3, 28, 11, 0, tzinfo=timezone.utc))
            page.goto(intake_url + "/?utm_source=google&utm_medium=cpc&utm_campaign=browser-proof&gclid=browser-click")
            page.get_by_role("button", name="Explore pricing").click()
            assert intake.status()["events"] == 0
            page.locator("#ads").check()
            for label in ("Allow analytics", "Explore pricing", "Talk to sales"):
                with page.expect_response("**/collect"):
                    page.get_by_role("button", name=label, exact=True).click()
            assert intake.status()["events"] == 3
            assert [e["event"] for e in page.evaluate("window.dataLayer")] == ["page_view", "pricing_view", "generate_lead"]
            page.screenshot(path=output / "browser-proof.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=workspace / "browser-mobile.png", full_page=True)
            page.get_by_role("button", name="Stop tracking").click()
            page.get_by_role("button", name="Explore pricing").click()
            assert intake.status()["events"] == 3 and page.evaluate("sessionStorage.length") == 0

            page = browser.new_page(viewport={"width": 1440, "height": 1220}, device_scale_factor=1)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(seller_url)
            page.locator("#token").fill(operator)
            page.get_by_role("button", name="Open workbench").click()
            page.locator("#model-badge").filter(has_text="Recorded inference").wait_for()
            assert page.locator("#generate").is_disabled()
            assert page.locator("#draft").input_value() == record["proposal"]["draft"]
            # Reapply the exact preserved reviewer edit through the actual UI.
            page.locator("#draft").fill(reviewed["proposal"]["draft"])
            page.get_by_role("button", name="Prepare governed review").click()
            page.get_by_text("Governed content prepared", exact=False).wait_for()
            page.get_by_role("button", name="Approve CRM task", exact=True).click()
            page.get_by_role("button", name="Deliver approved task", exact=True).click()
            page.locator(".receipt").wait_for()
            assert "Task persisted in the synthetic CRM" in page.locator(".receipt").inner_text()
            assert "Approval and delivery refer to the same content hash." in page.locator(".receipt").inner_text()
            for label in ("Approved actions", "Delivered tasks"):
                assert page.locator(".metric").filter(has_text=label).locator(".value").inner_text() == "1"
            # Return from the clicked delivery button to a genuine top-of-page viewport.
            page.evaluate("window.scrollTo(0,0)")
            draft_bounds = page.locator("#draft").bounding_box()
            viewport = {"width": 1440, "height": round(draft_bounds["y"] + draft_bounds["height"] + 18)}
            page.set_viewport_size(viewport)
            receipt_bounds = page.locator(".receipt").bounding_box()
            assert receipt_bounds["y"] >= 0 and receipt_bounds["y"] + receipt_bounds["height"] <= viewport["height"]
            assert page.locator(".receipt code").inner_text() == bench.overview()["actions"][0]["id"]
            page.screenshot(path=output / "seller-brief.jpg", type="jpeg", quality=92, full_page=False)
            page.screenshot(path=workspace / "seller-full.png", full_page=True)
            bounds = {name: page.locator(selector).bounding_box() for name, selector in
                      (("draft", "#draft"), ("receipt", ".receipt"), ("disclaimer", ".railfoot"))}
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("#accounts").is_visible()
            page.get_by_role("button", name="Permission withdrawn").click()
            page.get_by_role("heading", name="Permission withdrawn", exact=True).wait_for()
            page.screenshot(path=workspace / "seller-mobile.png", full_page=True)
            browser.close()
    with sqlite3.connect(workspace / "capture-crm.sqlite") as c:
        delivered = c.execute("SELECT body FROM seller_tasks").fetchall()
    assert len(delivered) == 1 and json.loads(delivered[0][0])["proposal"] == reviewed["proposal"]
    assert not errors, errors
    result = {"captured_utc": datetime.now(timezone.utc).isoformat(), "pages": "real local HTML/CSS/JS and HTTP APIs",
              "inference": "preserved recorded output; no new model request", "salesforce": "not accessed",
              "recorded_application_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "intake_events": 3, "local_delivered_tasks": 1, "mobile_overflow": False, "page_errors": errors,
              "seller_viewport": viewport, "seller_bounds": bounds,
              "reviewed_draft": "exact preserved reviewer edit, applied through UI",
              "approval_and_delivery_evidence_visible": True,
              "image_sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                               for name in ("browser-proof.png", "seller-brief.jpg")}}
    if output.resolve() == (ROOT / "docs/images").resolve():
        metadata = output / "ui-refresh.json"
        previous = json.loads(metadata.read_text(encoding="utf-8"))
        replacements = previous["screenshots"]
        for name, entry in replacements.items():
            if hashlib.sha256((ROOT / entry["archived_path"]).read_bytes()).hexdigest() != entry["original_sha256"]:
                raise RuntimeError("Original presentation archive changed")
            entry["current_sha256"] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        result.update(screenshots=replacements,
                      historical_native_acceptance_commit=previous["historical_native_acceptance_commit"],
                      seller_crop="Genuine viewport includes approval/delivery receipt and the complete reviewed draft; questions and cautions remain below the frame")
        metadata.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (workspace / "capture.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="Fresh isolated capture directory")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/images")
    args = parser.parse_args()
    capture(args.workspace, args.output)
