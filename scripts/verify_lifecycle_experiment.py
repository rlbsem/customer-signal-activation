"""Execute synthetic experiment controls, independent HTTP recovery, dbt and real browser checks."""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from signals.contracts import digest
from signals.harness import serve
from signals.lifecycle import Lifecycle
from signals.lifecycle_analytics import build
from signals.lifecycle_api import app as api
from signals.lifecycle_destination import app as destination
from signals.lifecycle_experiment import Experiments
from signals.lifecycle_fixtures import BASE, seed
from signals.lifecycle_study import STUDY, END, observe
from signals.remote import connect

ROOT = Path(__file__).resolve().parents[1]


def run(workspace, output):
    workspace, output = Path(workspace), Path(output)
    workspace.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=True)
    e = Lifecycle(workspace / "core.sqlite")
    seed(e)
    x = Experiments(e)
    x.register(STUDY)
    original = x.assign_all(STUDY, BASE)
    assert original == Experiments(Lifecycle(e.path)).assign_all(STUDY, BASE)
    with serve(destination(workspace / "destination.sqlite")) as url:
        actions = e.view(BASE)["actions"]
        candidates = []
        for a in original:
            action = next(v for v in actions if v["enrollment"] == a["enrollment"])
            if a["arm"] == "holdout":
                assert e.dispatch(action["id"], BASE, url) == "experiment_holdout"
            elif a["eligibility"] == "eligible":
                candidates.append(action)
        assert len(candidates) >= 2
        first, second = candidates[:2]
        for a in [first, second]:
            e.approve(a["id"], a["approval_hash"], BASE)
        assert e.dispatch(first["id"], BASE, url, lose_ack=True) == "uncertain"
        pending = x.measure(STUDY, BASE)
        assert sum(a["unresolved"] for a in pending["assignments"]) == 1
        assert sum(a["accepted"] for a in pending["assignments"]) == 0
        assert e.dispatch(first["id"], BASE, url) == "accepted"
        child = "from signals.lifecycle import Lifecycle;import sys;Lifecycle(sys.argv[1]).dispatch(sys.argv[2],int(sys.argv[3]),sys.argv[4],kill=True)"
        process = subprocess.run([sys.executable, "-c", child, e.path, second["id"], str(BASE), url])
        assert process.returncode == 86
        restarted = Lifecycle(e.path)
        assert restarted.dispatch(second["id"], BASE, url) == "accepted"
        for a in [first, second]:
            assert restarted.dispatch(a["id"], BASE, url) == "accepted"
        with connect(workspace / "destination.sqlite") as c:
            receipts = [json.loads(r[0]) for r in c.execute("SELECT body FROM receipts ORDER BY id")]
        assert {r["id"] for r in receipts} == {first["id"], second["id"]}
        assert all(
            r["payload_hash"] == digest(json.loads(next(a["payload"] for a in actions if a["id"] == r["id"])))
            for r in receipts
        )
    before = x.measure(STUDY, BASE)
    assert before["population"]["holdout"]["accepted"] == 0
    assert before["population"]["treatment"]["accepted"] == 2
    observe(e)
    initial = x.measure(STUDY, END)
    initial_sql = build(e, workspace / "incremental", as_of=END)
    observe(e, corrected=True)
    corrected = x.measure(STUDY, END + 1)
    incremental = build(e, workspace / "incremental", as_of=END + 1)
    full = build(e, workspace / "full", full=True, as_of=END + 1)
    assert incremental == full and incremental != initial_sql
    assert sum(a["converted"] for a in initial["assignments"]) == 4
    assert sum(a["converted"] for a in corrected["assignments"]) == 3
    assert x.measure(STUDY, END) == initial
    assert sum(a["pipeline_cents"] for a in initial["assignments"]) == 12500000
    assert sum(a["pipeline_cents"] for a in corrected["assignments"]) == 0
    # Larger scenario exercises assignment/source measurement and dbt, not network throughput.
    large = Lifecycle(workspace / "large.sqlite")
    seed(large, 1200)
    lx = Experiments(large)
    lx.register(STUDY)
    lx.assign_all(STUDY, BASE)
    observe(large, corrected=True)
    large_report = lx.measure(STUDY, END + 1)
    large_sql = build(large, workspace / "large-sql", as_of=END + 1)
    large_full = build(large, workspace / "large-full", full=True, as_of=END + 1)
    assert large_sql == large_full
    assert len(large_report["assignments"]) == 1200
    assert sum(a["converted"] for a in large_report["assignments"]) == 399
    assert not any(a["accepted"] for a in large_report["assignments"])
    browser_checks = capture(workspace, output)
    protected = (
        json.loads((ROOT / "work/experiment-baseline.json").read_text(encoding="utf8"))
        if (ROOT / "work/experiment-baseline.json").exists()
        else json.loads(
            (ROOT / "docs/evidence/lifecycle-experiment/baseline.json").read_text(encoding="utf8")
        )
    )
    for name, expected in protected["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    files = (
        list((ROOT / "src/signals").glob("lifecycle*.py"))
        + list((ROOT / "lifecycle_dbt").rglob("*.sql"))
        + [ROOT / "web/lifecycle.html", Path(__file__).resolve()]
    )
    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Local synthetic experiment; real loopback HTTP, independent receipt SQLite, child exit 86, native DuckDB/dbt. No vendor or customer communication.",
        "reference_people": 12,
        "large_people": 1200,
        "source_sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        "assignment_restart_equal": True,
        "worker_exit": process.returncode,
        "independent_receipts": receipts,
        "uncertain_before_readback": pending,
        "pending_observation": before,
        "initial": initial,
        "corrected": corrected,
        "incremental_full_parity": True,
        "dbt_models": list(full["models"]),
        "large": {k: v for k, v in large_report.items() if k not in {"assignments", "source_records"}},
        "large_source_digest": digest(large_report),
        "browser": browser_checks,
        "preserved_artifacts": len(protected["files"]),
        "screenshots": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob("*.png")},
    }
    (output / "execution.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf8")
    print(
        json.dumps(
            {
                "reference": 12,
                "large": 1200,
                "receipt_effects": len(receipts),
                "worker_exit": process.returncode,
                "dbt_models": len(full["models"]),
                "parity": True,
                "browser": browser_checks,
                "preserved": len(protected["files"]),
            }
        )
    )


def capture(workspace, output):
    from playwright.sync_api import sync_playwright

    # Independent UI fixture exercises the same operator API; no recorded data injected into HTML.
    with (
        serve(destination(workspace / "browser-remote.sqlite")) as remote,
        serve(api(workspace / "browser.sqlite", remote, "synthetic-study-only")) as url,
        sync_playwright() as pw,
    ):
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        page.locator(".action").first.wait_for()
        page.get_by_role("button", name="Experiment & Outcomes", exact=True).click()
        assert page.locator("#study-empty").is_visible()
        page.locator("#token").fill("synthetic-study-only")

        def act(label, operation):
            page.get_by_role("button", name=label, exact=True).click()
            page.wait_for_function(
                "op=>document.querySelector('#notice').textContent.includes(op+' result')", arg=operation
            )

        act("Assign reference study", "start_experiment")
        page.locator("#study-rows tr").first.wait_for()
        # Deliver the eligible synthetic treatment in the original operations screen.
        page.get_by_role("button", name="Lifecycle operations", exact=True).click()
        page.locator("#person").select_option("synthetic-0007")
        card = page.locator(".action").filter(
            has=page.get_by_role("heading", name="Quiet-trial assistance", exact=True)
        )
        card.get_by_role("button", name="Approve exact action").click()
        page.wait_for_function("document.querySelector('#notice').textContent.includes('approve result')")
        card.get_by_role("button", name="Lose acknowledgment").click()
        page.wait_for_function("document.querySelector('#notice').textContent.includes('lose_ack result')")
        card.get_by_role("button", name="Reconcile receipt").click()
        page.wait_for_function("document.querySelector('#notice').textContent.includes('reconcile result')")
        page.get_by_role("button", name="Experiment & Outcomes", exact=True).click()
        act("Load arm-neutral synthetic outcomes", "observe_experiment")
        assert page.locator("#study-rows tr").count() == 12
        assert "125,000" in page.locator("#study-exceptions").inner_text()
        page.locator("#study-person").select_option("synthetic-0007")
        page.evaluate("scrollTo(0,0)")
        page.screenshot(path=str(output / "experiment-desktop.png"), full_page=True)
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("scrollTo(0,0)")
        page.screenshot(path=str(output / "experiment-mobile.png"), full_page=True)
        assert page.locator("body").evaluate("e=>e.scrollWidth<=innerWidth")
        page.locator("#study-inspector").locator("..").locator("summary").click()
        assert "payload_hash" in page.locator("#study-inspector").inner_text()
        act("Apply late source correction", "observe_experiment")
        assert "USD" not in page.locator("#study-estimate").inner_text()  # No fabricated financial lift.
        page.wait_for_function("document.querySelector('#study-exceptions').textContent.includes('$0')")
        assert "$0" in page.locator("#study-exceptions").inner_text()
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.getAttribute('role')") == "region" or page.evaluate(
            "document.activeElement.tagName"
        ) in {
            "INPUT",
            "BUTTON",
            "SELECT",
            "SUMMARY",
            "A",
        }
        assert page.locator("button").evaluate_all("es=>es.every(e=>!!e.textContent.trim())")
        assert not errors, errors
        browser.close()
    return {
        "desktop": "1440x1100",
        "mobile": "390x844",
        "horizontal_overflow": False,
        "operator_flow": "assignment, exact approval, lost ack, receipt readback, mature outcome, late correction",
        "console_errors": errors,
        "keyboard_labels": "passed",
    }


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
