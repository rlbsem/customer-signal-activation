import os
import subprocess
import sys

import httpx
import pytest

from signals.contracts import canonical
from signals.decision import plan
from signals.fixtures import AS_OF, event
from signals.remote import connect
from signals.store import Store
from signals.worker import deliver_one


def first(store):
    with store.tx() as c:
        return dict(c.execute("SELECT * FROM outbox ORDER BY rowid LIMIT 1").fetchone())


@pytest.mark.parametrize("mode", ["timeout_after_commit", "rate_limit", "unavailable"])
def test_network_failure_restart_and_receipt_reconciliation(store, remote, mode):
    path, url = remote
    plan(store, AS_OF)
    key = first(store)["id"]
    with connect(path) as c:
        c.execute("INSERT INTO faults VALUES(?,?)", (key, mode))
    deliver_one(store, url, AS_OF, timeout=0.1)
    assert first(store)["state"] == "uncertain"
    # A new Store instance models reopening persisted state; actual process death tested below.
    reopened = Store(store.path)
    deliver_one(reopened, url, AS_OF + 2)
    assert first(store)["state"] == "applied"
    with connect(path) as c:
        assert c.execute("SELECT count(*) FROM receipts WHERE id=?", (key,)).fetchone()[0] == 1
        assert c.execute("SELECT revision FROM contacts WHERE id='cedar:account-0000'").fetchone()[0] == 1


def test_consent_revocation_between_plan_and_send_blocks_stale_work(store, remote):
    plan(store, AS_OF)
    store.ingest(
        event("consent", {"account": "account-0000", "allowed": False, "revision": 2}, "revoke"),
        "privacy",
        AS_OF,
    )
    deliver_one(store, remote[1], AS_OF)
    assert first(store)["state"] == "blocked"
    with connect(remote[0]) as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def test_sales_owned_remote_conflict_is_not_retried_blindly(store, remote):
    plan(store, AS_OF)
    with connect(remote[0]) as c:
        c.execute(
            "INSERT INTO contacts VALUES(?,?,?)",
            ("cedar:account-0000", 1, canonical({"owner": "manual-owner"})),
        )
    deliver_one(store, remote[1], AS_OF)
    assert first(store)["state"] == "conflict"


def test_remote_unowned_fields_survive(store, remote):
    plan(store, AS_OF)
    with connect(remote[0]) as c:
        c.execute(
            "INSERT INTO contacts VALUES(?,?,?)",
            ("cedar:account-0000", 1, canonical({"sales_note": "Keep this"})),
        )
    deliver_one(store, remote[1], AS_OF)
    with httpx.Client(trust_env=False) as client:
        assert (
            client.get(remote[1] + "/contacts/cedar:account-0000").json()["properties"]["sales_note"]
            == "Keep this"
        )


def test_real_process_death_after_remote_commit_has_one_effect(store, remote):
    plan(store, AS_OF)
    script = (
        "import os; from signals.store import Store; from signals.worker import deliver_one; "
        "deliver_one(Store(os.environ['TEST_DB']),os.environ['TEST_REMOTE'],1774958400,crash=lambda:os._exit(86))"
    )
    env = dict(os.environ, TEST_DB=str(store.path), TEST_REMOTE=remote[1])
    result = subprocess.run([sys.executable, "-c", script], env=env)
    assert result.returncode == 86
    assert first(store)["state"] == "pending"
    deliver_one(store, remote[1], AS_OF)
    assert first(store)["detail"] == "reconciled_remote_commit"
    with connect(remote[0]) as c:
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1


def test_remote_optimistic_revision_rejects_stale_writer(remote):
    payload = {
        "external_id": "cedar:a",
        "score": 10,
        "owner": "cedar-east",
        "lifecycle": "nurture",
        "campaign": "x",
        "decision_id": "d",
    }
    with httpx.Client(base_url=remote[1], trust_env=False) as client:
        assert (
            client.post("/apply/crm/one", json={"payload": payload, "expected_revision": 0}).status_code
            == 200
        )
        assert (
            client.post("/apply/crm/two", json={"payload": payload, "expected_revision": 0}).status_code
            == 409
        )
