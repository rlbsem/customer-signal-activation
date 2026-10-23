"""Explicit arm-neutral synthetic outcome source used by the reproducible demonstration."""

from .lifecycle import DAY
from .lifecycle_experiment import Experiments
from .lifecycle_fixtures import BASE

STUDY = "quiet-trial-v1"
END = BASE + 7 * DAY


def observe(engine, *, corrected=False):
    study = Experiments(engine)
    rows = study.measure(STUDY, BASE)["assignments"]
    for a in rows:
        person = a["person"]
        study.coverage("observation-" + person, 1, a["brand"], person, BASE, END, END)
        # Assignment and acceptance are deliberately not inputs to the outcome rule.
        if int(person.rsplit("-", 1)[1]) % 3 == 0:
            engine.ingest(
                a["brand"],
                person,
                "crm",
                "outcome-" + person,
                1,
                BASE + DAY,
                END,
                "conversion",
                {"converted": True},
            )
    first = min(a["person"] for a in rows)
    study.value("opportunity-001", 1, "cedar", first, "outcome-" + first, 12500000, END)
    study.value("unmapped-002", 1, "cedar", first, "missing-conversion", 900000, END)
    if corrected:
        engine.ingest(
            "cedar",
            first,
            "crm",
            "outcome-" + first,
            2,
            BASE + DAY,
            END + 1,
            "conversion",
            {"converted": False},
        )
    return END + int(corrected)
