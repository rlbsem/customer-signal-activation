"""Create-only seller review records; native Salesforce acceptance is pending.

No marketing messages or standard Tasks are sent. An acknowledgement means only
that the exact approved payload was read back from the review inbox.
"""
import json
import re
from urllib.parse import urlsplit

import httpx

from .contracts import canonical, digest
from .salesforce_contract import DeliveryError, EnvironmentAttestation, MappingBook, OrganizationApproval

API = "/services/data/v65.0"
OBJECT = "Seller_Action__c"
FIELDS = {"Action_Key__c": 64, "Payload_Hash__c": 64, "Payload__c": 32768,
          "Brand__c": 80, "Account_Key__c": 120, "Proposed_Owner__c": 120,
          "Mapping_Hash__c": 64, "Subject__c": 160, "Proposed_Action__c": 80,
          "Draft__c": 4000, "Review_Notice__c": 255}
LOOKUPS = {"Synthetic_Account__c": "Synthetic_Account__c", "Proposed_User__c": "User"}
NOTICE = "SYNTHETIC DEMONSTRATION: review only; no message sent or commercial action executed."


def native_client(instance_url, access_token):
    parsed = urlsplit(instance_url)
    if (parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".my.salesforce.com")
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise DeliveryError("invalid_salesforce_origin")
    if not access_token or any(c.isspace() for c in access_token):
        raise DeliveryError("invalid_access_token")
    return httpx.Client(base_url=instance_url.rstrip("/"), timeout=10,
                        trust_env=False, follow_redirects=False,
                        headers={"Authorization": "Bearer " + access_token, "updateMru": "false"})


def _key(key):
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
        raise DeliveryError("invalid_action_key")


def _body(payload, mapping):
    required = {"run_id", "brand", "account", "owner", "proposal", "evidence_hash"}
    if not isinstance(payload, dict) or set(payload) not in (required, required | {"execution"}):
        raise DeliveryError("invalid_approved_payload")
    if "execution" in payload:
        proof = payload["execution"]
        if (not isinstance(proof, dict) or set(proof) != {"version", "authorities"}
                or proof["version"] != "seller-execution/v1" or not isinstance(proof["authorities"], list)
                or len(proof["authorities"]) > 4):
            raise DeliveryError("invalid_execution_proof")
        ids = set()
        for item in proof["authorities"]:
            if (not isinstance(item, dict) or set(item) != {"id", "sha256"}
                    or not isinstance(item["id"], str) or item["id"] in ids
                    or not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])):
                raise DeliveryError("invalid_execution_proof")
            ids.add(item["id"])
    for name in ("run_id", "brand", "account", "owner", "evidence_hash"):
        if not isinstance(payload[name], str) or not payload[name]:
            raise DeliveryError("invalid_approved_payload")
    if not isinstance(payload["proposal"], dict):
        raise DeliveryError("invalid_approved_payload")
    proposal = payload["proposal"]
    if (proposal.get("action") not in ("schedule_discovery", "clarify_need", "support_handoff")
            or not isinstance(proposal.get("draft"), str) or not proposal["draft"]):
        raise DeliveryError("review_action_required")
    entry = mapping.resolve(payload)
    value = {"Action_Key__c": digest(payload), "Payload_Hash__c": digest(payload),
             "Payload__c": canonical(payload), "Brand__c": payload["brand"],
             "Account_Key__c": payload["account"], "Proposed_Owner__c": payload["owner"],
             "Mapping_Hash__c": digest(entry), "Synthetic_Account__c": entry["registry_id"],
             "Proposed_User__c": entry["user_id"], "Subject__c": "Synthetic seller review: " + proposal["action"],
             "Proposed_Action__c": proposal["action"], "Draft__c": proposal["draft"], "Review_Notice__c": NOTICE}
    # Salesforce field lengths are bounded conservatively in UTF-16 code units.
    if any(len(value[k].encode("utf-16-le")) // 2 > size for k, size in FIELDS.items()):
        raise DeliveryError("payload_exceeds_field_limit")
    return value


class SalesforceInbox:
    def __init__(self, client, approval, mapping):
        if not isinstance(approval, OrganizationApproval) or not isinstance(mapping, MappingBook):
            raise DeliveryError("explicit_approval_and_mapping_required")
        self.client, self.approval, self.mapping = client, approval, mapping
        self.ready = False
        self.environment_attestation = None
        self._preflight_destination_pin = None

    @property
    def destination_pin(self):
        return digest({"org": self.approval.org_id, "environment": self.approval.environment,
                       "edition": self.approval.organization_type, "mapping": self.mapping.fingerprint})

    def _request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, API + path, **kwargs)
        except httpx.TransportError:
            raise DeliveryError("transport_outcome_unknown", retryable=True) from None
        return response

    @staticmethod
    def _json(response):
        try:
            return response.json()
        except ValueError:
            raise DeliveryError("invalid_response_json") from None

    def _require_success(self, response):
        if 200 <= response.status_code < 300:
            return
        code = None
        try:
            errors = response.json()
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                code = errors[0].get("errorCode")
        except ValueError:
            pass
        if response.status_code == 429 or code == "REQUEST_LIMIT_EXCEEDED":
            delay = response.headers.get("Retry-After", "")
            delay = min(int(delay), 3600) if delay.isdigit() else None
            raise DeliveryError("rate_limited", True, delay)
        if response.status_code in (401, 403):
            raise DeliveryError("authentication_or_permission_denied")
        if response.status_code >= 500:
            raise DeliveryError("server_outcome_unknown", True)
        raise DeliveryError("unexpected_http_status")

    def preflight(self, attestation=None):
        self.ready = False
        self.environment_attestation = None
        if attestation is None:
            # Direct adapters must independently verify the environment too. Restricted
            # native roles instead receive the live administrator's in-process attestation.
            response = self._request("GET", "/query", params={
                "q": "SELECT Id, IsSandbox, OrganizationType FROM Organization"})
            self._require_success(response)
            org = self._json(response)
            records = org.get("records") if isinstance(org, dict) else None
            if (not isinstance(org, dict) or org.get("done") is not True or org.get("totalSize") != 1
                    or not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict)):
                raise DeliveryError("approved_environment_mismatch")
            self.approval.verify(records[0])
        elif not isinstance(attestation, EnvironmentAttestation) or attestation.approval != self.approval:
            raise DeliveryError("approved_environment_mismatch")
        else:
            self.environment_attestation = attestation
        response = self._request("GET", f"/sobjects/{OBJECT}/describe")
        self._require_success(response)
        schema = self._json(response)
        if (not isinstance(schema, dict) or schema.get("name") != OBJECT
                or schema.get("createable") is not True or schema.get("queryable") is not True
                or schema.get("updateable") is not False or schema.get("deletable") is not False):
            raise DeliveryError("create_only_permission_contract_required")
        raw_fields = schema.get("fields")
        if not isinstance(raw_fields, list):
            raise DeliveryError("field_contract_missing")
        fields = {f["name"]: f for f in raw_fields
                  if isinstance(f, dict) and isinstance(f.get("name"), str)}
        for name, size in FIELDS.items():
            field = fields.get(name, {})
            expected_type = "textarea" if name in ("Payload__c", "Draft__c") else "string"
            if (field.get("createable") is not True or type(field.get("length")) is not int
                    or field["length"] < size or field.get("type") != expected_type):
                raise DeliveryError("field_contract_missing")
        external = fields["Action_Key__c"]
        if external.get("unique") is not True or external.get("externalId") is not True:
            raise DeliveryError("unique_external_key_required")
        for name, target in LOOKUPS.items():
            field = fields.get(name, {})
            if (field.get("type") != "reference" or field.get("createable") is not True
                    or field.get("referenceTo") != [target]):
                raise DeliveryError("lookup_contract_missing")
        self.ready = True
        self._preflight_destination_pin = self.destination_pin
        return {"environment_pin_verified": True, "environment": self.approval.environment,
                "organization_type": self.approval.organization_type, "schema_sha256": digest(schema),
                "create_only": True, "unique_external_key": True}

    def validate_mapping(self, payload):
        entry = self.mapping.resolve(payload)
        response = self._request("GET", "/sobjects/Synthetic_Account__c/" + entry["registry_id"])
        self._require_success(response)
        account = self._json(response)
        expected = {"Id": entry["registry_id"], "Account_Key__c": entry["brand"] + ":" + entry["account"],
                    "Brand__c": entry["brand"], "Approved_Owner__c": entry["user_id"],
                    "Active__c": True, "Synthetic__c": True}
        if not isinstance(account, dict) or any(account.get(k) != v for k, v in expected.items()):
            raise DeliveryError("remote_mapping_mismatch")
        response = self._request("GET", "/sobjects/User/" + entry["user_id"], params={"fields": "Id,IsActive"})
        self._require_success(response)
        user = self._json(response)
        if not isinstance(user, dict) or user.get("Id") != entry["user_id"] or user.get("IsActive") is not True:
            raise DeliveryError("proposed_user_inactive_or_mismatched")

    def receipt(self, key):
        if not self.ready or self._preflight_destination_pin != self.destination_pin:
            raise DeliveryError("preflight_required")
        _key(key)
        response = self._request("GET", f"/sobjects/{OBJECT}/Action_Key__c/{key}")
        if response.status_code == 404:
            # Absence/access ambiguity never authorizes an update or blind upsert.
            return None
        self._require_success(response)
        record = self._json(response)
        try:
            payload = json.loads(record["Payload__c"])
            expected = _body(payload, self.mapping)
            if expected["Action_Key__c"] != key or any(record.get(k) != v for k, v in expected.items()):
                raise ValueError
            record_id = record["Id"]
            if not isinstance(record_id, str) or not re.fullmatch(r"[a-zA-Z0-9]{15}(?:[a-zA-Z0-9]{3})?", record_id):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise DeliveryError("receipt_content_conflict") from None
        return {"id": key, "payload_hash": key, "destination": "salesforce_review_inbox",
                "record_id": record_id}

    def create(self, key, payload):
        if not self.ready or self._preflight_destination_pin != self.destination_pin:
            raise DeliveryError("preflight_required")
        _key(key)
        body = _body(payload, self.mapping)
        if body["Action_Key__c"] != key:
            raise DeliveryError("payload_key_conflict")
        prior = self.receipt(key)
        if prior:
            return prior
        self.validate_mapping(payload)
        response = self._request("POST", f"/sobjects/{OBJECT}/", json=dict(body, Review_Status__c="Pending"))
        # A competing create may have won the database uniqueness race.
        duplicate = False
        if response.status_code == 400:
            value = self._json(response)
            duplicate = (isinstance(value, list) and len(value) == 1
                         and isinstance(value[0], dict) and value[0].get("errorCode") == "DUPLICATE_VALUE")
        if not duplicate:
            self._require_success(response)
        # Never accept a create acknowledgement alone; reread the exact immutable payload.
        receipt = self.receipt(key)
        if receipt is None:
            raise DeliveryError("created_record_not_visible", True)
        return receipt


def bridge(inbox, token):
    """Adapter for the existing workbench HTTP contract. Bind to loopback only."""
    import secrets
    from fastapi import FastAPI, Header, HTTPException
    api = FastAPI(title="Salesforce seller review inbox bridge")

    def authorize(authorization):
        if not token or not secrets.compare_digest(authorization, "Bearer " + token):
            raise HTTPException(401)

    def call(method, *args):
        try:
            return method(*args)
        except DeliveryError as exc:
            raise HTTPException(503 if exc.retryable else 409, str(exc),
                                headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else None) from None

    @api.get("/health")
    def health():
        return {"ready": inbox.ready, "native_acceptance": "not_established_by_health"}

    @api.get("/seller/receipts/{key}")
    def receipt(key: str, authorization: str = Header(default="")):
        authorize(authorization)
        result = call(inbox.receipt, key)
        if result is None:
            raise HTTPException(404)
        return result

    @api.post("/seller/tasks/{key}")
    def create(key: str, payload: dict, authorization: str = Header(default="")):
        authorize(authorization)
        return call(inbox.create, key, payload)

    return api
