"""Deterministic fixtures; every repeated block of twelve has independently stated cases."""

from .lifecycle import DAY

BASE = 1768845600  # 2026-01-19 18:00 UTC, daytime in Toronto.
EXPECTED = [
    "eligible",
    "permission_denied",
    "coverage_missing_or_expired",
    "owner_review",
    "eligible",
    "owner_changed",
    "recent_activity",
    "eligible",
    "permission_denied",
    "eligible",
    "eligible",
    "eligible",
]


def seed(engine, count=12):
    for i in range(count):
        person = f"synthetic-{i:04d}"
        case = i % 12
        state = "customer" if case in {3, 4} else "trial"
        values = [
            (
                "crm",
                "identity",
                {"account": f"synthetic-account-{i // 3}", "owner": "owner-a", "zone": "America/Toronto"},
            ),
            (
                "crm",
                "commercial",
                {"state": state, "opportunity": case == 3, "owner": "owner-b" if case == 5 else "owner-a"},
            ),
            (
                "preferences",
                "preference",
                {"channel": "email", "purpose": "marketing", "allowed": case not in {1, 8}},
            ),
            ("product", "trial", {"started": True}),
            ("product", "coverage", {"after": BASE - 3 * DAY, "through": BASE}),
        ]
        if case == 2:
            values = [v for v in values if v[1] != "coverage"]
        if case == 6:
            values.append(("product", "activity", {"active": True}))
        for source, kind, body in values:
            at = BASE if kind in {"activity", "coverage"} else BASE - DAY
            engine.ingest("cedar", person, source, f"{person}-{kind}", 1, at, at, kind, body)
    return engine.tick(BASE)
