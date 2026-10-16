"""Real loopback HTTP against an explicit Salesforce contract emulator, not Salesforce."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from signals.contracts import digest
from signals.harness import serve
from signals.salesforce_delivery import (
    API, FIELDS, LOOKUPS, OBJECT, DeliveryError, SalesforceInbox, bridge, native_client,
)
from signals.salesforce_contract import MappingBook, OrganizationApproval

ORG = "00D000000000001AAA"
APPROVAL = OrganizationApproval(ORG, "sandbox", "Enterprise Edition", True)
ENTRY = {"brand": "cedar", "account": "account-0012", "owner": "cedar-east",
         "registry_id": "a01000000000001AAA", "user_id": "005000000000001AAA"}


def mapping():
    return MappingBook([ENTRY])


@pytest.fixture
def payload():
    return {"run_id": "synthetic-run", "brand": "cedar", "account": "account-0012",
            "owner": "cedar-east", "evidence_hash": "e" * 64,
            "proposal": {"action": "schedule_discovery", "draft": "Which workflow matters most?"}}


@pytest.fixture
def remote(tmp_path):
    path = tmp_path / "contract-emulator.sqlite"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE records(key TEXT PRIMARY KEY, body TEXT)")
    state = {"org": ORG, "sandbox": True, "edition": "Enterprise Edition", "account": {
        "Id": ENTRY["registry_id"], "Account_Key__c": "cedar:account-0012", "Brand__c": "cedar",
        "Approved_Owner__c": ENTRY["user_id"], "Active__c": True, "Synthetic__c": True},
        "user": {"Id": ENTRY["user_id"], "IsActive": True}, "schema": {
        "name": OBJECT, "createable": True, "queryable": True, "updateable": False, "deletable": False,
        "fields": [{"name": k, "length": n, "createable": True,
                    "type": "textarea" if k in ("Payload__c", "Draft__c") else "string",
                    "unique": k == "Action_Key__c", "externalId": k == "Action_Key__c"}
                   for k, n in FIELDS.items()] + [
                       {"name": k, "createable": True, "type": "reference", "referenceTo": [v]}
                       for k, v in LOOKUPS.items()]}, "requests": [], "fault": None, "path": path}
    api = FastAPI()

    @api.get("/services/oauth2/userinfo")
    def who(request: Request):
        token = request.headers.get("authorization")
        user = {"Bearer reviewer-test-token": "005000000000002AAA",
                "Bearer admin-test-token": "005000000000003AAA"}.get(token, ENTRY["user_id"])
        return {"organization_id": state["org"], "user_id": user}

    @api.get("/health")
    def health():
        return {"ready": True}

    @api.api_route(API + "/{route:path}", methods=["GET", "POST", "PATCH", "DELETE"])
    async def sf(route: str, request: Request):
        state["requests"].append((request.method, route))
        token = request.headers.get("authorization")
        if token not in ("Bearer test-only-token", "Bearer reviewer-test-token", "Bearer admin-test-token"):
            return JSONResponse([{"errorCode": "INVALID_SESSION_ID"}], status_code=401)
        reviewer = token == "Bearer reviewer-test-token"
        if state["fault"] in ("401", "403", "429", "500", "redirect", "nonjson"):
            fault = state["fault"]
            if fault == "redirect":
                return JSONResponse({}, 302, headers={"Location": "https://outside.invalid"})
            if fault == "nonjson":
                from fastapi.responses import Response
                return Response("private-debug-content", 200)
            return JSONResponse([{"errorCode": "REQUEST_LIMIT_EXCEEDED" if fault == "429" else "DENIED",
                                  "message": "private-debug-content"}], int(fault), headers={"Retry-After": "3"})
        if route == "query":
            query = request.query_params.get("q", "")
            if "Profile.PermissionsViewAllData" in query:
                return {"done": True, "totalSize": 1, "records": [
                    {"Profile": {"PermissionsViewAllData": state.get("admin_view_all", True)}}]}
            if "SELECT Id FROM Seller_Action__c" in query:
                with sqlite3.connect(path) as c:
                    rows = [json.loads(r[0]) for r in c.execute("SELECT body FROM records")]
                return {"done": True, "totalSize": len(rows), "records": [{"Id": r["Id"]} for r in rows]}
            if "COUNT(Id)" in query:
                key = query.split("Action_Key__c='")[1].split("'")[0]
                with sqlite3.connect(path) as c:
                    n = c.execute("SELECT count(*) FROM records WHERE key=?", (key,)).fetchone()[0]
                return {"done": True, "totalSize": 1, "records": [{"n": n}]}
            if " WHERE Id='" in query:
                record_id = query.split(" WHERE Id='")[1].split("'")[0]
                if " FROM Synthetic_Account__c " in query:
                    rows = [state["account"]] if record_id == state["account"]["Id"] else []
                else:
                    with sqlite3.connect(path) as c:
                        rows = [json.loads(r[0]) for r in c.execute("SELECT body FROM records")]
                    rows = [r for r in rows if r["Id"] == record_id]
                return {"done": True, "totalSize": len(rows), "records": rows}
            return {"done": True, "totalSize": 1,
                    "records": [{"Id": state["org"], "IsSandbox": state["sandbox"],
                                 "OrganizationType": state["edition"]}]}
        if route == f"sobjects/{OBJECT}/describe":
            if reviewer:
                schema = json.loads(json.dumps(state["schema"]))
                schema.update(createable=state.get("reviewer_createable", False), updateable=True)
                for field in schema["fields"]:
                    field.update(createable=False, updateable=False)
                schema["fields"] += [{"name": n, "updateable": True} for n in ("Review_Status__c", "Reviewer_Notes__c")]
                return schema
            return state["schema"]
        if route == "sobjects/Account/describe":
            return {"createable": False, "updateable": False, "deletable": False}
        if route == "sobjects/Synthetic_Account__c/describe":
            return {"createable": False, "updateable": False, "deletable": False, "queryable": True}
        if request.method == "GET" and route == "sobjects/Synthetic_Account__c/" + ENTRY["registry_id"]:
            return state["account"]
        if request.method == "GET" and route == "sobjects/User/" + ENTRY["user_id"]:
            return state["user"]
        if request.method in ("PATCH", "DELETE"):
            body = await request.json() if request.method == "PATCH" else {}
            if not reviewer or request.method == "DELETE" or set(body) - {"Review_Status__c", "Reviewer_Notes__c"}:
                if not reviewer and state.get("mutation_changes_record"):
                    with sqlite3.connect(path) as c:
                        key, raw = c.execute("SELECT key,body FROM records").fetchone()
                        record = dict(json.loads(raw), Subject__c="unexpected mutation")
                        c.execute("UPDATE records SET body=? WHERE key=?", (json.dumps(record), key))
                return JSONResponse([{"errorCode": state.get("mutation_code", "INSUFFICIENT_ACCESS") if not reviewer else "INSUFFICIENT_ACCESS",
                    "message": "insufficient access rights on object id"}], state.get("mutation_status", 403) if not reviewer else 403)
            with sqlite3.connect(path) as c:
                rows = c.execute("SELECT key,body FROM records").fetchall()
                assert len(rows) == 1
                record = dict(json.loads(rows[0][1]), **body)
                c.execute("UPDATE records SET body=? WHERE key=?", (json.dumps(record), rows[0][0]))
            from fastapi.responses import Response
            return Response(status_code=204)
        if request.method == "GET":
            key = route.rsplit("/", 1)[-1]
            with sqlite3.connect(path) as c:
                row = c.execute("SELECT body FROM records WHERE key=?", (key,)).fetchone()
                if not row and len(key) == 18:
                    row = c.execute("SELECT body FROM records").fetchone()
            return json.loads(row[0]) if row else JSONResponse([{"errorCode": "NOT_FOUND"}], 404)
        assert request.method == "POST" and route == f"sobjects/{OBJECT}/"
        if reviewer and not state.get("reviewer_allows_create"):
            return JSONResponse([{"errorCode": state.get("reviewer_create_code", "INSUFFICIENT_ACCESS")}],
                                state.get("reviewer_create_status", 403))
        body = await request.json()
        if (body.get("Brand__c") != state["account"]["Brand__c"]
                or state["account"]["Active__c"] is not True or state["account"]["Synthetic__c"] is not True
                or body.get("Proposed_User__c") != state["account"]["Approved_Owner__c"]):
            return JSONResponse([{"errorCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION"}], 400)
        key = body["Action_Key__c"]
        body["Id"] = "a00" + key[:15]
        with sqlite3.connect(path) as c:
            try:
                c.execute("INSERT INTO records VALUES(?,?)", (key, json.dumps(body)))
            except sqlite3.IntegrityError:
                return JSONResponse([{"errorCode": "DUPLICATE_VALUE"}], 400)
        if state["fault"] == "after_commit":
            state["fault"] = None
            return JSONResponse([{"errorCode": "UNKNOWN"}], 503)
        return JSONResponse({"id": body["Id"], "success": True, "errors": []}, 201)

    with serve(api) as url, httpx.Client(base_url=url, trust_env=False, follow_redirects=False,
                                        headers={"Authorization": "Bearer test-only-token"}) as client:
        inbox = SalesforceInbox(client, APPROVAL, mapping())
        inbox.preflight()
        yield inbox, state


def count(state):
    with sqlite3.connect(state["path"]) as c:
        return c.execute("SELECT count(*) FROM records").fetchone()[0]


def test_create_readback_and_replay_without_updates(remote, payload):
    inbox, state = remote
    key = digest(payload)
    first = inbox.create(key, payload)
    assert first == inbox.create(key, payload) == inbox.receipt(key)
    assert count(state) == 1
    assert len([r for r in state["requests"] if r[0] == "POST"]) == 1
    assert not any(r[0] in ("PATCH", "DELETE") for r in state["requests"])


def test_lost_acknowledgement_reconciles_persisted_record(remote, payload):
    inbox, state = remote
    state["fault"] = "after_commit"
    with pytest.raises(DeliveryError, match="server_outcome_unknown"):
        inbox.create(digest(payload), payload)
    assert count(state) == 1
    assert inbox.create(digest(payload), payload)["payload_hash"] == digest(payload)
    assert len([r for r in state["requests"] if r[0] == "POST"]) == 1


def test_competing_creates_reconcile_database_unique_constraint(remote, payload, monkeypatch):
    inbox, state = remote
    real_receipt = inbox.receipt
    barrier = threading.Barrier(2)
    local = threading.local()

    def racing_receipt(key):
        if not getattr(local, "initial_read", False):
            local.initial_read = True
            result = real_receipt(key)
            barrier.wait(timeout=5)
            return result
        return real_receipt(key)

    monkeypatch.setattr(inbox, "receipt", racing_receipt)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: inbox.create(digest(payload), payload), range(2)))
    assert results[0] == results[1] and count(state) == 1
    assert len([r for r in state["requests"] if r[0] == "POST"]) == 2


@pytest.mark.parametrize("field", ["Payload_Hash__c", "Payload__c", "Brand__c", "Account_Key__c", "Proposed_Owner__c"])
def test_tampered_receipt_blocks_without_overwrite(remote, payload, field):
    inbox, state = remote
    key = digest(payload)
    inbox.create(key, payload)
    with sqlite3.connect(state["path"]) as c:
        row = json.loads(c.execute("SELECT body FROM records WHERE key=?", (key,)).fetchone()[0])
        row[field] = "tampered"
        c.execute("UPDATE records SET body=? WHERE key=?", (json.dumps(row), key))
    with pytest.raises(DeliveryError, match="receipt_content_conflict"):
        inbox.create(key, payload)
    assert count(state) == 1


@pytest.mark.parametrize("change", ["org", "sandbox", "unique", "external", "field", "write", "delete"])
def test_preflight_fail_closed(remote, change, payload):
    inbox, state = remote
    if change == "org":
        state["org"] = "00D000000000002AAA"
    elif change == "sandbox":
        state["sandbox"] = False
    elif change in ("unique", "external"):
        state["schema"]["fields"][0]["unique" if change == "unique" else "externalId"] = False
    elif change == "field":
        state["schema"]["fields"][0]["createable"] = False
    else:
        state["schema"]["updateable" if change == "write" else "deletable"] = True
    with pytest.raises(DeliveryError):
        inbox.preflight()
    with pytest.raises(DeliveryError, match="preflight_required"):
        inbox.create(digest(payload), payload)
    assert count(state) == 0


@pytest.mark.parametrize("fault,retryable", [("401", False), ("403", False), ("429", True),
                                            ("500", True), ("redirect", False), ("nonjson", False)])
def test_errors_are_bounded_sanitized_and_do_not_create(remote, payload, fault, retryable):
    inbox, state = remote
    state["fault"] = fault
    with pytest.raises(DeliveryError) as error:
        inbox.create(digest(payload), payload)
    assert error.value.retryable is retryable
    assert "private-debug-content" not in str(error.value)
    assert count(state) == 0
    if fault == "429":
        assert error.value.retry_after == 3


@pytest.mark.parametrize("url", ["http://foo.my.salesforce.com", "https://salesforce.com.evil.invalid",
                                 "https://foo.my.salesforce.com@evil.invalid", "https://127.0.0.1",
                                 "https://foo.my.salesforce.com/path", "https://foo.my.salesforce.com?x=1"])
def test_native_transport_rejects_unsafe_origins(url):
    with pytest.raises(DeliveryError):
        native_client(url, "not-a-real-token")


def test_content_bound_key_and_field_bounds(remote, payload):
    inbox, state = remote
    with pytest.raises(DeliveryError, match="payload_key_conflict"):
        inbox.create("0" * 64, payload)
    payload["proposal"]["draft"] = "x" * 40000
    with pytest.raises(DeliveryError, match="payload_exceeds_field_limit"):
        inbox.create(digest(payload), payload)
    assert count(state) == 0


def test_existing_workbench_delivers_approved_content_through_bridge(remote, tmp_path):
    # Reuse the existing clearly labelled handwritten software-test responder.
    from test_seller import SyntheticResponder
    from signals.fixtures import AS_OF
    from signals.seller import Workbench
    from signals.seller_fixtures import seed_workbench
    from signals.store import Refused, Store
    inbox, state = remote
    bench = Workbench(Store(tmp_path / "workbench.sqlite"), SyntheticResponder(), AS_OF)
    seed_workbench(bench)
    record = bench.generate("cedar", "account-0012")
    with serve(bridge(inbox, "bridge-test-token")) as url:
        with pytest.raises(Refused, match="action_not_approved"):
            bench.deliver("not-approved", url, "bridge-test-token")
        approved = bench.approve(record["id"], record["proposal"], digest(record))
        assert bench.deliver(approved["id"], url, "wrong")["state"] == "retry"
        assert count(state) == 0
        result = bench.deliver(approved["id"], url, "bridge-test-token")
        assert result["destination"] == "salesforce_review_inbox"
        assert result == bench.deliver(approved["id"], url, "bridge-test-token")
    assert count(state) == 1


def test_workbench_lost_acknowledgement_recovery(remote, tmp_path):
    from test_seller import SyntheticResponder
    from signals.fixtures import AS_OF
    from signals.seller import Workbench
    from signals.seller_fixtures import seed_workbench
    from signals.store import Store
    inbox, state = remote
    bench = Workbench(Store(tmp_path / "workbench.sqlite"), SyntheticResponder(), AS_OF)
    seed_workbench(bench)
    record = bench.generate("cedar", "account-0012")
    approved = bench.approve(record["id"], record["proposal"], digest(record))
    state["fault"] = "after_commit"
    with serve(bridge(inbox, "bridge-test-token")) as url:
        assert bench.deliver(approved["id"], url, "bridge-test-token")["state"] == "retry"
        assert count(state) == 1
        assert bench.deliver(approved["id"], url, "bridge-test-token")["record_id"]
        assert count(state) == 1


@pytest.mark.parametrize("malformed", [None, {}, [{"name": "Payload__c", "length": "32768"}]])
def test_malformed_field_metadata_fails_closed(remote, malformed):
    inbox, state = remote
    state["schema"]["fields"] = malformed
    with pytest.raises(DeliveryError, match="field_contract_missing"):
        inbox.preflight()
    assert not inbox.ready


def test_wrong_field_type_fails_closed(remote):
    inbox, state = remote
    state["schema"]["fields"][0]["type"] = "int"
    with pytest.raises(DeliveryError, match="field_contract_missing"):
        inbox.preflight()
    assert not inbox.ready


@pytest.mark.parametrize("records", [None, [None], ["bad"]])
def test_malformed_org_response_is_sanitized(records):
    def respond(request):
        return httpx.Response(200, json={"done": True, "totalSize": 1, "records": records})
    with httpx.Client(transport=httpx.MockTransport(respond), base_url="https://test.invalid") as client:
        inbox = SalesforceInbox(client, APPROVAL, mapping())
        with pytest.raises(DeliveryError, match="approved_environment_mismatch"):
            inbox.preflight()
        assert not inbox.ready


def test_transport_timeout_and_salesforce_403_limit_are_sanitized():
    def timeout(request):
        raise httpx.ReadTimeout("private-response-detail", request=request)
    with httpx.Client(transport=httpx.MockTransport(timeout), base_url="https://test.invalid") as client:
        inbox = SalesforceInbox(client, APPROVAL, mapping())
        with pytest.raises(DeliveryError, match="transport_outcome_unknown") as error:
            inbox.preflight()
        assert error.value.retryable
        assert not inbox.ready
    with pytest.raises(DeliveryError, match="rate_limited") as error:
        inbox._require_success(httpx.Response(403, json=[{"errorCode": "REQUEST_LIMIT_EXCEEDED"}],
                                             headers={"Retry-After": "999999"}))
    assert error.value.retryable and error.value.retry_after == 3600
