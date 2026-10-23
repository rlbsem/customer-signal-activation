"""Reproducible lifecycle execution and browser capture, isolated from prior evidence."""

import json
import hashlib
import sys
from pathlib import Path
from signals.lifecycle import Lifecycle
from signals.lifecycle_fixtures import BASE, seed
from signals.lifecycle_destination import app as destination
from signals.lifecycle_api import app
from signals.lifecycle_analytics import build
from signals.harness import serve
from signals.remote import connect


def run(workspace, output):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=False)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    e = Lifecycle(workspace / "core.sqlite")
    seed(e)
    with serve(destination(workspace / "destination.sqlite")) as url:
        for person, journey in [(0, "quiet"), (4, "expansion")]:
            a = next(
                r
                for r in e.view(BASE)["actions"]
                if r["person"] == f"synthetic-{person:04d}" and r["journey"] == journey
            )
            e.approve(a["id"], a["approval_hash"], BASE)
            assert e.dispatch(a["id"], BASE, url, lose_ack=True) == "uncertain"
            assert e.dispatch(a["id"], BASE, url) == "accepted"
        onboarding = next(
            r
            for r in e.tick(BASE + 86400)["actions"]
            if r["person"] == "synthetic-0000" and r["journey"] == "onboarding"
        )
        e.approve(onboarding["id"], onboarding["approval_hash"], BASE + 86400)
        assert e.dispatch(onboarding["id"], BASE + 86400, url) == "accepted"
        with connect(workspace / "destination.sqlite") as c:
            independent = [json.loads(r[0]) for r in c.execute("SELECT body FROM receipts ORDER BY id")]
        assert len(independent) == 3
        # Browser operates a separate fresh fixture, so source/report evidence is not silently changed.
        from playwright.sync_api import sync_playwright

        with (
            serve(destination(workspace / "browser-destination.sqlite")) as browser_url,
            serve(app(workspace / "browser.sqlite", browser_url, "lifecycle-local-review")) as ui,
            sync_playwright() as pw,
        ):
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.goto(ui)
            page.locator(".action").first.wait_for()
            page.locator("#token").fill("lifecycle-local-review")
            card = page.locator(".action").filter(
                has=page.get_by_role("heading", name="Quiet-trial assistance", exact=True)
            )
            card.get_by_role("button", name="Approve exact action").click()
            page.wait_for_function("document.querySelector('#notice').textContent.includes('approve result')")
            card.get_by_role("button", name="Lose acknowledgment").click()
            page.wait_for_function(
                "document.querySelector('#notice').textContent.includes('lose_ack result')"
            )
            card.get_by_role("button", name="Reconcile receipt").click()
            page.wait_for_function(
                "document.querySelector('#notice').textContent.includes('reconcile result')"
            )
            assert card.locator(".badge").inner_text().startswith("accepted")
            page.screenshot(path=str(output / "lifecycle-desktop.png"), full_page=True)
            assert page.locator("body").evaluate("(e)=>e.scrollWidth<=innerWidth")
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(output / "lifecycle-mobile.png"), full_page=True)
            assert page.locator("body").evaluate("(e)=>e.scrollWidth<=innerWidth")
            page.get_by_role("button", name="Record conversion").click()
            page.wait_for_function("document.querySelector('#notice').textContent.includes('convert result')")
            assert page.locator(".action").filter(has_text="cancelled").count() >= 1
            page.set_viewport_size({"width": 1440, "height": 1100})
            page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement.tagName") in {
                "BUTTON",
                "INPUT",
                "SELECT",
                "SUMMARY",
                "A",
            }
            assert page.locator("button").evaluate_all("es=>es.every(e=>e.textContent.trim().length>0)")
            browser.close()
    e.ingest(
        "cedar", "synthetic-0000", "crm", "conversion-demo", 1, BASE, BASE, "conversion", {"converted": True}
    )
    initial = build(e, workspace / "incremental")
    e.ingest(
        "cedar",
        "synthetic-0000",
        "crm",
        "conversion-demo",
        2,
        BASE - 1,
        BASE + 1,
        "conversion",
        {"converted": False},
    )
    corrected = build(e, workspace / "incremental")
    full = build(e, workspace / "full", True)
    assert corrected == full
    large = Lifecycle(workspace / "large.sqlite")
    large_view = seed(large, 1200)
    from datetime import datetime, timezone

    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {
            str(p.resolve().relative_to(Path(__file__).resolve().parents[1])).replace(chr(92), "/"): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in list(Path("src/signals").glob("lifecycle*.py"))
            + list(Path("lifecycle_dbt").rglob("*.sql"))
            + [Path("web/lifecycle.html"), Path(__file__)]
        },
        "scope": "Executed local synthetic lifecycle; no native marketing-platform or email execution",
        "reference_people": 12,
        "large_people": 1200,
        "large_enrollments": len(large_view["timers"]),
        "independent_receipts": independent,
        "initial_analytics": initial,
        "corrected_analytics": corrected,
        "incremental_full_parity": True,
        "desktop_mobile": "passed",
        "screenshots": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob("*.png")},
    }
    (output / "execution.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf8")
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k
                not in {"initial_analytics", "corrected_analytics", "independent_receipts", "screenshots"}
            }
        )
    )


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
