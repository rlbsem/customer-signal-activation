"""Closed source-specific contracts; browser data cannot claim server authority."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Id = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")]
Brand = Literal["cedar", "harbour"]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timestamp required")
    return int(dt.timestamp())


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Web(Closed):
    session: Id
    action: Literal["page_view", "pricing_view", "contact_sales"]
    analytics_consent: bool
    ads_consent: bool
    campaign: Annotated[str, Field(max_length=80)] = ""
    source: Annotated[str, Field(max_length=80)] = ""
    medium: Annotated[str, Field(max_length=40)] = ""
    gclid: Annotated[str, Field(max_length=120, pattern=r"^[A-Za-z0-9_-]*$")] = ""

    @model_validator(mode="after")
    def tracking_requires_consent(self):
        if not self.analytics_consent:
            raise ValueError("analytics denied: do not collect browser events")
        if self.gclid and not self.ads_consent:
            raise ValueError("click ID requires ads consent")
        return self


class Link(Closed):
    session: Id
    account: Id
    evidence: Annotated[str, Field(min_length=8, max_length=200)]


class Profile(Closed):
    account: Id
    region: Literal["ON", "BC", "OTHER"]
    owner: Id | None = None
    employees: Annotated[int, Field(ge=0, le=1000000)] | None = None
    revision: Annotated[int, Field(ge=1)]


class Enrichment(Closed):
    account: Id
    provider: Literal["primary", "fallback"]
    employees: Annotated[int, Field(ge=0, le=1000000)]
    revision: Annotated[int, Field(ge=1)]


class Consent(Closed):
    account: Id
    allowed: bool
    revision: Annotated[int, Field(ge=1)]


class Call(Closed):
    account: Id
    call_id: Id
    qualified: bool
    campaign: Annotated[str, Field(max_length=80)] = ""


class Opportunity(Closed):
    account: Id
    opportunity: Id
    stage: Literal["open", "won", "lost"]
    revision: Annotated[int, Field(ge=1)]


class Fulfillment(Closed):
    opportunity: Id
    fulfillment: Id
    completed: bool
    revision: Annotated[int, Field(ge=1)]


class Invoice(Closed):
    fulfillment: Id
    invoice: Id
    cents: Annotated[int, Field(gt=0, le=1000000000)]


class Payment(Closed):
    invoice: Id
    allocation: Id
    cents: Annotated[int, Field(gt=0, le=1000000000)]


MODELS = {
    "web": Web,
    "link": Link,
    "profile": Profile,
    "enrichment": Enrichment,
    "consent": Consent,
    "call": Call,
    "opportunity": Opportunity,
    "fulfillment": Fulfillment,
    "invoice": Invoice,
    "payment": Payment,
}
AUTHORITIES = {
    "web": "browser",
    "link": "crm",
    "profile": "crm",
    "opportunity": "crm",
    "enrichment": "enrichment",
    "consent": "privacy",
    "call": "telephony",
    "fulfillment": "operations",
    "invoice": "finance",
    "payment": "finance",
}


class Event(Closed):
    schema_version: Literal[2]
    event_id: Id
    brand: Brand
    kind: Literal[
        "web",
        "link",
        "profile",
        "enrichment",
        "consent",
        "call",
        "opportunity",
        "fulfillment",
        "invoice",
        "payment",
    ]
    occurred_at: str
    data: dict

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, v):
        if type(v) is not int:
            raise ValueError("schema_version must be an integer token")
        return v

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, v):
        timestamp(v)
        return v

    @model_validator(mode="after")
    def typed_data(self):
        self.data = MODELS[self.kind].model_validate(self.data).model_dump()
        return self


def now():
    return int(datetime.now(timezone.utc).timestamp())
