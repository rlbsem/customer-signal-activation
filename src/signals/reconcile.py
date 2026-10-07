import json

import httpx


def reconcile(store, remote):
    with store.tx() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM outbox WHERE state='applied' ORDER BY rowid")]
        unresolved = [
            dict(r)
            for r in c.execute(
                "SELECT id,state,detail FROM outbox WHERE state NOT IN ('applied','blocked') ORDER BY rowid"
            )
        ]
    expected = {}
    for row in rows:
        payload = json.loads(row["payload"])
        if row["destination"] == "crm":
            expected[payload["external_id"]] = payload
    differences = []
    with httpx.Client(base_url=remote, timeout=2, trust_env=False) as client:
        for key, payload in expected.items():
            response = client.get("/contacts/" + key)
            response.raise_for_status()
            actual = response.json()["properties"]
            if any(actual.get(k) != v for k, v in payload.items()):
                differences.append(key)
        for row in rows:
            if row["destination"] == "conversion":
                payload = json.loads(row["payload"])
                response = client.get("/conversions/" + payload["order_id"])
                if response.status_code != 200 or response.json() != payload:
                    differences.append(payload["order_id"])
    return {
        "matched": not differences and not unresolved,
        "crm_accounts_checked": len(expected),
        "applied_operations_checked": len(rows),
        "differences": differences,
        "unresolved": unresolved,
    }
