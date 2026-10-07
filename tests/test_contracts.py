from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from signals.api import app
from signals.contracts import AUTHORITIES
from signals.fixtures import AS_OF, event, sources
from signals.store import Refused


def test_replay_and_changed_identity(store):
    e = next(sources(1))
    assert store.ingest(e, "crm", AS_OF)["duplicate"]
    e["data"]["region"] = "BC"
    with pytest.raises(Refused, match="payload_conflict"):
        store.ingest(e, "crm", AS_OF)


@pytest.mark.parametrize("change", ["version", "extra", "timestamp", "pii", "consent", "click"])
def test_closed_browser_contract(store, change):
    e = next(e for e in sources(1) if e["kind"] == "web")
    e = deepcopy(e)
    if change == "version":
        e["schema_version"] = 99
    elif change == "extra":
        e["account"] = "forged"
    elif change == "timestamp":
        e["occurred_at"] = "2026-03-01T00:00:00"
    elif change == "pii":
        e["data"]["email"] = "synthetic@example.test"
    elif change == "consent":
        e["data"]["analytics_consent"] = False
    else:
        e["data"]["ads_consent"] = False
    with pytest.raises(ValidationError):
        store.ingest(e, "browser", AS_OF)


def test_browser_cannot_forge_crm_or_privacy(store):
    client = TestClient(app(store, {"private-crm": "crm"}))
    e = next(sources(1))
    assert client.post("/collect", json=e).status_code == 422
    assert client.post("/events", json=e).status_code == 401
    assert client.post("/events", json=e, headers={"Authorization": "Bearer private-crm"}).status_code == 200
    assert client.get("/status").status_code == 401


@pytest.mark.parametrize("kind", ["payment", "invoice", "link", "profile", "call"])
def test_new_transport_id_cannot_duplicate_entity(store, kind):
    e = next(e for e in sources(12) if e["kind"] == kind)
    e["event_id"] = "another-transport-id"
    with pytest.raises(Refused, match="entity_revision"):
        store.ingest(e, AUTHORITIES[kind], AS_OF)


def test_concurrent_identical_admission_has_one_receipt(store):
    e = event("consent", {"account": "new", "allowed": True, "revision": 1}, "concurrent")
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: store.ingest(e, "privacy", AS_OF), range(8)))
    assert len({r["seq"] for r in results}) == 1
    assert sum(not r["duplicate"] for r in results) == 1
