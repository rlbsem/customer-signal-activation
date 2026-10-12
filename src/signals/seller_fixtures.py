"""Explicit synthetic inquiry documents; original commercial fixture is untouched."""

from .fixtures import AS_OF, seed

NOTES = {
    "account-0012": ("Discovery request", "We coordinate approvals across regional teams using spreadsheets. "
                     "Handoffs are missed and account reporting takes too long. We want to understand "
                     "workflow coordination and reporting before evaluating integration requirements. "
                     "Our operations team can meet next week. We have not agreed a budget."),
    "account-0000": ("Customer support call", "We are an existing customer. The approval workflow stopped "
                     "after yesterday's configuration change. Please involve support before discussing "
                     "any expansion. Our team needs help investigating the incident."),
    "account-0002": ("Early inquiry", "We are reviewing several ways to organise our work. "
                     "We have not identified a specific workflow or agreed who owns the project. "
                     "Please ask about our requirements before recommending a meeting."),
    "account-0004": ("Historical inquiry", "We previously asked about workflow coordination. "
                     "Do not treat this old note as current permission to contact us."),
    "account-0006": ("Routing inquiry", "We want a workflow discovery session. "
                     "Please confirm the account territory and owner before any handoff."),
    "account-0008": ("Conflicting account information", "Our team is considering account reporting. "
                     "The account size information has not been verified; please clarify it first."),
}


def seed_workbench(workbench):
    with workbench.store.tx() as c:
        empty = not c.execute("SELECT 1 FROM events").fetchone()
    if empty:
        seed(workbench.store, 24)
    for account, (title, text) in NOTES.items():
        workbench.document({"id": "inquiry-" + account, "brand": "cedar", "account": account,
                            "revision": 1, "title": title, "kind": "inquiry",
                            "occurred_at": "2026-03-30T12:00:00Z", "text": text}, "synthetic_seed")
    return AS_OF
