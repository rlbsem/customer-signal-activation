import json

import pytest
from playwright.sync_api import sync_playwright
from pydantic import ValidationError

from signals.api import app
from signals.contracts import Event
from signals.fixtures import AS_OF, sources
from signals.harness import serve
from signals.store import Refused, Store


def test_previous_wire_version_is_rejected():
    envelope = next(sources(1))
    envelope["schema_version"] = 1
    with pytest.raises(ValidationError):
        Event.model_validate(envelope)


def test_previous_persisted_contract_requires_new_workspace(tmp_path):
    path = tmp_path / "earlier.sqlite"
    store = Store(path)
    store.ingest(next(sources(1)), "crm", AS_OF)
    with store.tx() as c:
        body = json.loads(c.execute("SELECT body FROM events").fetchone()[0])
        body["schema_version"] = 1
        c.execute("UPDATE events SET body=?", (json.dumps(body),))
    with pytest.raises(Refused, match="unsupported_stored_contract"):
        Store(path)


def test_versioned_b2b_sources_keep_explicit_fulfillment_grain():
    rows = list(sources(12))
    assert all(r["schema_version"] == 2 for r in rows)
    fulfillments = [r for r in rows if r["kind"] == "fulfillment"]
    assert len(fulfillments) == 4
    assert len({(r["brand"], r["data"]["fulfillment"]) for r in fulfillments}) == 4
    assert all(
        set(r["data"]) == {"opportunity", "fulfillment", "completed", "revision"} for r in fulfillments
    )
    assert {r["data"]["action"] for r in rows if r["kind"] == "web"} == {
        "page_view",
        "pricing_view",
        "contact_sales",
    }


def test_business_unit_branding_and_session_context_agree(tmp_path):
    store = Store(tmp_path / "brand.sqlite")
    with serve(app(store, {})) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url + "/?brand=harbour&utm_campaign=enterprise-workflows")
        assert page.title() == "Harbour Solutions · Enterprise workflow solutions"
        assert "HARBOUR SOLUTIONS" in page.locator("#brand-label").inner_text()
        with page.expect_response("**/collect"):
            page.get_by_role("button", name="Allow analytics").click()
        with page.expect_response("**/collect"):
            page.get_by_role("button", name="Talk to sales").click()
        with store.tx() as c:
            events = store.events(c, 9999999999)
        assert all(e["brand"] == "harbour" for e in events)
        assert events[-1]["data"]["action"] == "contact_sales"
        browser.close()
