import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from signals.analytics import build
from signals.api import app
from signals.contracts import AUTHORITIES
from signals.decision import plan
from signals.finance import plan_conversions
from signals.fixtures import AS_OF, sources
from signals.harness import serve
from signals.remote import connect
from signals.store import Store
from signals.worker import deliver_one


def test_actual_browser_to_crm_fulfillment_cash_feedback(tmp_path, remote):
    store = Store(tmp_path / "browser.sqlite")
    tokens = {f"demo-{actor}": actor for actor in set(AUTHORITIES.values())}
    with serve(app(store, tokens)) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.clock.install(time=datetime(2026, 3, 28, 11, 0, tzinfo=timezone.utc))
        page.goto(url + "/?utm_source=google&utm_medium=cpc&utm_campaign=browser-proof&gclid=browser-click")
        page.get_by_role("button", name="Explore pricing").click()
        assert store.status()["events"] == 0
        page.locator("#ads").check()
        with page.expect_response("**/collect"):
            page.get_by_role("button", name="Allow analytics").click()
        with page.expect_response("**/collect"):
            page.get_by_role("button", name="Explore pricing").click()
        with page.expect_response("**/collect"):
            page.get_by_role("button", name="Talk to sales").click()
        layer = page.evaluate("window.dataLayer")
        assert [e["event"] for e in layer] == ["page_view", "pricing_view", "generate_lead"]
        assert all(set(e) == {"event", "brand", "campaign", "source", "medium"} for e in layer)
        with store.tx() as c:
            web = store.events(c, AS_OF)
        session = web[0]["data"]["session"]
        assert all(e["data"]["gclid"] == "browser-click" for e in web)
        # CRM association is separately authenticated; browser cannot choose an account.
        with httpx.Client(base_url=url, trust_env=False) as client:
            for e in sources(1):
                if e["kind"] == "web":
                    continue
                if e["kind"] == "link":
                    e["data"]["session"] = session
                response = client.post(
                    "/events", json=e, headers={"Authorization": "Bearer demo-" + AUTHORITIES[e["kind"]]}
                )
                assert response.status_code == 200, response.text
        decisions = plan(store, AS_OF)
        assert decisions[0]["score"] == 80 and decisions[0]["campaign"] == "browser-proof"
        plan_conversions(store, AS_OF)
        while deliver_one(store, remote[1], AS_OF):
            pass
        report = build(store, AS_OF, tmp_path / "warehouse")
        assert report["cash_cents"] == 105000
        assert report["campaigns"][0]["campaign"] == "browser-proof"
        with connect(remote[0]) as c:
            assert c.execute("SELECT count(*) FROM conversions").fetchone()[0] == 4
            props = json.loads(c.execute("SELECT body FROM contacts").fetchone()[0])
            assert props["owner"] == "cedar-east" and props["lifecycle"] == "customer"
        screenshot = os.environ.get("SIGNALS_SCREENSHOT")
        if screenshot:
            Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=screenshot, full_page=True)
        page.get_by_role("button", name="Stop tracking").click()
        before = store.status()["events"]
        page.get_by_role("button", name="Explore pricing").click()
        assert store.status()["events"] == before
        assert page.evaluate("sessionStorage.length") == 0
        browser.close()


def test_campaign_survives_navigation_but_not_revocation(tmp_path):
    store = Store(tmp_path / "navigation.sqlite")
    with serve(app(store, {})) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url + "/?utm_campaign=original&gclid=click")
        page.locator("#ads").check()
        with page.expect_response("**/collect"):
            page.get_by_role("button", name="Allow analytics").click()
        page.goto(url + "/")
        with page.expect_response("**/collect"):
            page.get_by_role("button", name="Allow analytics").click()
        with store.tx() as c:
            rows = store.events(c, 9999999999)
        assert rows[-1]["data"]["campaign"] == "original"
        assert rows[-1]["data"]["gclid"] == ""  # Ads permission default denied on the new document.
        page.get_by_role("button", name="Stop tracking").click()
        page.goto(url + "/")
        with page.expect_response("**/collect"):
            page.get_by_role("button", name="Allow analytics").click()
        with store.tx() as c:
            rows = store.events(c, 9999999999)
        assert rows[-1]["data"]["campaign"] == ""
        browser.close()


def test_lost_collection_ack_reuses_event_id(tmp_path):
    store = Store(tmp_path / "lost-ack.sqlite")
    with serve(app(store, {})) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        attempts = []

        def intercept(route):
            attempts.append(route.request.post_data_json["event_id"])
            response = route.fetch()
            if len(attempts) == 1:
                route.fulfill(status=503, body="Lost collection acknowledgement")
            else:
                route.fulfill(response=response)

        page.route("**/collect", intercept)
        page.goto(url + "/?utm_campaign=retry-proof")
        page.get_by_role("button", name="Allow analytics").click()
        page.wait_for_function("document.querySelector('#receipt').textContent.startsWith('Session ')")
        assert len(attempts) == 2 and attempts[0] == attempts[1]
        assert store.status()["events"] == 1
        assert len(page.evaluate("window.dataLayer")) == 1
        browser.close()
