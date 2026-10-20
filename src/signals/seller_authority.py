"""Bounded executable language; model prose and retrieved documents confer no authority.

This controls a finite internal-review contract, not general semantic entailment.
Trusted local bootstrap code owns operational assertions; there is no grant HTTP API.
"""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import digest
from .store import Refused

VERSION = "seller-execution/v1"
ISSUERS = {
    "support_operations": {"availability", "staffing", "escalation", "timing"},
    "commercial_operations": {"pricing", "commitment"},
}
ALLOWED = {
    "qualified": {"schedule_discovery", "clarify_need"},
    "customer": {"support_handoff", "clarify_need"},
    "nurture": {"clarify_need"},
}
NEUTRAL = {
    "schedule_discovery": "Which requirements and preferred meeting times should the account owner review?",
    "clarify_need": "Which requirement needs clarification before the account owner considers a next step?",
    "support_handoff": "Please provide the observed error and approximate time of the change for internal review.",
}


class Authority(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[a-zA-Z0-9._:-]{1,100}$")
    brand: Literal["cedar", "harbour"]
    account: str = Field(min_length=1, max_length=120)
    owner: str = Field(min_length=1, max_length=120)
    action: Literal["schedule_discovery", "clarify_need", "support_handoff"]
    kind: Literal["availability", "staffing", "escalation", "pricing", "timing", "commitment"]
    issuer: Literal["support_operations", "commercial_operations"]
    statement: str = Field(min_length=8, max_length=500)
    valid_from: int
    expires_at: int
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def bounded(self):
        if self.kind not in ISSUERS[self.issuer] or not 0 < self.expires_at - self.valid_from <= 86400:
            raise ValueError("authority_role_or_validity_invalid")
        return self


SCHEMA = """
CREATE TABLE IF NOT EXISTS seller_authorities(
 id TEXT PRIMARY KEY, body TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TRIGGER IF NOT EXISTS authority_body_immutable BEFORE UPDATE OF id,body ON seller_authorities
 BEGIN SELECT RAISE(ABORT,'immutable operational authority'); END;
CREATE TRIGGER IF NOT EXISTS authority_no_delete BEFORE DELETE ON seller_authorities
 BEGIN SELECT RAISE(ABORT,'retained operational authority'); END;
CREATE TRIGGER IF NOT EXISTS authority_no_unrevoke BEFORE UPDATE OF revoked ON seller_authorities
 WHEN OLD.revoked=1 AND NEW.revoked<>1
 BEGIN SELECT RAISE(ABORT,'authority revocation is terminal'); END;
"""


def resolve(c, ids, snapshot, clock):
    if (not isinstance(ids, list) or len(ids) > 4 or any(not isinstance(i, str) for i in ids)
            or len(ids) != len(set(ids))):
        raise Refused("invalid_authority_selection")
    records = []
    for identity in ids:
        row = c.execute("SELECT body,revoked FROM seller_authorities WHERE id=?", (identity,)).fetchone()
        if not row or row["revoked"]:
            raise Refused("operational_authority_absent_or_revoked")
        record = Authority.model_validate(json.loads(row["body"])).model_dump()
        if (record["brand"], record["account"], record["owner"]) != (
                snapshot["brand"], snapshot["account"], snapshot["decision"]["owner"]):
            raise Refused("operational_authority_scope_mismatch")
        if not record["valid_from"] <= clock < record["expires_at"]:
            raise Refused("operational_authority_not_current")
        records.append(record)
    # Two currently selected assertions about one capability are ambiguous. A replacement
    # requires explicit revocation rather than letting the model resolve a conflict.
    if len({r["kind"] for r in records}) != len(records):
        raise Refused("conflicting_operational_authority")
    for chosen in records:
        for row in c.execute("SELECT body FROM seller_authorities WHERE revoked=0"):
            other = json.loads(row[0])
            if (other["id"] != chosen["id"] and all(other[k] == chosen[k] for k in
                    ("brand", "account", "owner", "action", "kind"))
                    and other["valid_from"] <= clock < other["expires_at"]):
                raise Refused("conflicting_operational_authority")
    return records


def compile_proposal(proposal, snapshot, records):
    action = proposal["action"]
    if action == "no_action":
        raise Refused("no_action_is_not_deliverable")
    if action not in ALLOWED.get(snapshot["decision"]["stage"], set()):
        raise Refused("action_outside_verified_stage")
    if any(r["action"] != action for r in records):
        raise Refused("operational_authority_action_mismatch")
    draft = NEUTRAL[action]
    if records:
        draft += "\n\n" + "\n".join(r["statement"] for r in records)
    return {
        "assessment": "Internal review of the attached source excerpts; excerpts are untrusted evidence.",
        "action": action,
        "claims": proposal["claims"],
        "draft": draft,
        "questions": [NEUTRAL[action]],
        "uncertainties": ["No customer contact or unlisted operational commitment is authorized by this record."],
    }


def proof(records):
    return {"version": VERSION, "authorities": [{"id": r["id"], "sha256": digest(r)} for r in records]}
