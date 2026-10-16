"""Explicit environment approval and pinned synthetic destination mappings."""
from dataclasses import dataclass
import re

from .contracts import digest


class DeliveryError(ValueError):
    def __init__(self, code, retryable=False, retry_after=None):
        super().__init__(code)
        self.retryable, self.retry_after = retryable, retry_after


def sf_id(value, prefix=None):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9]{18}", value)
            or (prefix and not value.startswith(prefix))):
        raise DeliveryError("invalid_pinned_id")
    return value


@dataclass(frozen=True)
class OrganizationApproval:
    org_id: str
    environment: str
    organization_type: str
    approved: bool

    def __post_init__(self):
        sf_id(self.org_id, "00D")
        if (self.approved is not True or self.environment not in ("sandbox", "developer_edition")
                or not isinstance(self.organization_type, str) or not self.organization_type
                or (self.environment == "developer_edition" and self.organization_type != "Developer Edition")):
            raise DeliveryError("explicit_environment_approval_required")

    def verify(self, org):
        if (not isinstance(org, dict) or org.get("Id") != self.org_id
                or org.get("OrganizationType") != self.organization_type
                or org.get("IsSandbox") is not (self.environment == "sandbox")):
            raise DeliveryError("approved_environment_mismatch")


@dataclass(frozen=True)
class EnvironmentAttestation:
    """In-process result of authenticated Organization verification, never loaded from JSON."""
    approval: OrganizationApproval
    observer_user_id: str

    def __post_init__(self):
        sf_id(self.observer_user_id, "005")

    def public(self):
        return {"administrator_environment_verified": True,
                "organization_reference_sha256": digest(self.approval.org_id),
                "administrator_reference_sha256": digest(self.observer_user_id),
                "organization_type": self.approval.organization_type,
                "environment": self.approval.environment}


class MappingBook:
    """Snapshot the allowlist; receipt checks never depend on mutable registry state."""
    def __init__(self, entries):
        self._entries = {}
        for raw in entries:
            if (not isinstance(raw, dict) or set(raw) != {
                    "brand", "account", "owner", "registry_id", "user_id"}
                    or any(not isinstance(v, str) or not v for v in raw.values())
                    or raw["brand"] not in ("cedar", "harbour")
                    or not re.fullmatch(r"account-[0-9]{4,8}", raw["account"])):
                raise DeliveryError("invalid_synthetic_mapping")
            sf_id(raw["registry_id"])
            sf_id(raw["user_id"], "005")
            key = (raw["brand"], raw["account"], raw["owner"])
            if key in self._entries or any(e["registry_id"] == raw["registry_id"] for e in self._entries.values()):
                raise DeliveryError("ambiguous_mapping")
            self._entries[key] = dict(raw)
        if not self._entries:
            raise DeliveryError("synthetic_mapping_required")

    @property
    def fingerprint(self):
        return digest(sorted(self._entries.values(), key=lambda e: (e["brand"], e["account"], e["owner"])))

    def resolve(self, payload):
        entry = self._entries.get((payload["brand"], payload["account"], payload["owner"]))
        if entry is None:
            raise DeliveryError("account_owner_mapping_not_approved")
        return dict(entry)
