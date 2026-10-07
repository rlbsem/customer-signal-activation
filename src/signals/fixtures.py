"""Synthetic business inputs; source amounts determine outputs, not dashboard targets."""

from datetime import datetime, timezone

from .contracts import AUTHORITIES, timestamp

AS_OF = timestamp("2026-03-31T12:00:00Z")


def event(kind, data, key, brand="cedar", day=28):
    return {
        "schema_version": 2,
        "event_id": key,
        "brand": brand,
        "kind": kind,
        "occurred_at": f"2026-03-{day:02}T12:00:00Z",
        "data": data,
    }


def sources(count=120):
    for i in range(count):
        brand = "cedar" if i % 2 == 0 else "harbour"
        account, session = f"account-{i:04}", f"session-{i:04}"
        scenario = (i // 2) % 6

        def e(kind, data, suffix, day=28):
            return event(kind, data, f"{account}-{suffix}", brand, day)

        yield e(
            "profile",
            {
                "account": account,
                "region": "OTHER" if scenario == 3 else "ON",
                "employees": None,
                "revision": 1,
            },
            "profile",
        )
        yield e(
            "link",
            {
                "account": account,
                "session": session,
                "evidence": "CRM verified B2B sales inquiry association",
            },
            "link",
        )
        yield e("consent", {"account": account, "allowed": scenario != 2, "revision": 1}, "consent")
        yield e(
            "enrichment",
            {
                "account": account,
                "provider": "primary",
                "employees": 8 if scenario == 1 else 80,
                "revision": 1,
            },
            "enrich",
        )
        if scenario == 4:
            yield e(
                "enrichment",
                {"account": account, "provider": "fallback", "employees": 5, "revision": 1},
                "conflict",
            )
        if scenario == 5:
            yield e(
                "call",
                {
                    "account": account,
                    "call_id": f"call-{i}",
                    "qualified": True,
                    "campaign": "partner-referral",
                },
                "call",
            )
        else:
            for n, action in enumerate(["page_view", "pricing_view", "contact_sales"]):
                yield e(
                    "web",
                    {
                        "session": session,
                        "action": action,
                        "analytics_consent": True,
                        "ads_consent": True,
                        "campaign": "enterprise-workflows",
                        "source": "google",
                        "medium": "cpc",
                        "gclid": f"synthetic-click-{i}",
                    },
                    f"web-{n}",
                )
        # Commercial source events are supplied independently of score. Two scenario
        # classes close real won/completed fulfillments; consent alone does not create revenue.
        if scenario == 0 and (i // 12) % 2 == 1:
            yield e(
                "opportunity",
                {"account": account, "opportunity": f"opp-{i}", "stage": "open", "revision": 1},
                "opp",
                29,
            )
        elif scenario in (0, 5):
            yield e(
                "opportunity",
                {"account": account, "opportunity": f"opp-{i}", "stage": "won", "revision": 1},
                "opp",
                29,
            )
            yield e(
                "fulfillment",
                {
                    "opportunity": f"opp-{i}",
                    "fulfillment": f"fulfillment-{i}",
                    "completed": True,
                    "revision": 1,
                },
                "fulfillment",
                30,
            )
            for part in range(2):
                cents = 50000 + (i % 9) * 10000 + part * 5000
                invoice = f"invoice-{i}-{part}"
                yield e(
                    "invoice",
                    {"fulfillment": f"fulfillment-{i}", "invoice": invoice, "cents": cents},
                    f"inv-{part}",
                    30,
                )
                for allocation in range(2):
                    yield e(
                        "payment",
                        {
                            "invoice": invoice,
                            "allocation": f"payment-{i}-{part}-{allocation}",
                            "cents": cents // 2,
                        },
                        f"pay-{part}-{allocation}",
                        31,
                    )


def seed(store, count=120):
    for e in sources(count):
        store.ingest(e, AUTHORITIES[e["kind"]], AS_OF)


def utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()
