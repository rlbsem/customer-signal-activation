"""Loopback operator application; independent acceptance destination, synthetic-only controls."""

import secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from .lifecycle import Lifecycle
from .lifecycle_fixtures import BASE, seed
from .remote import connect
from .store import Refused

ROOT = Path(__file__).resolve().parents[2]


def app(path, destination, token):
    engine = Lifecycle(path)
    with connect(path) as c:
        c.execute("CREATE TABLE IF NOT EXISTS lifecycle_clock(id INTEGER PRIMARY KEY,value INTEGER)")
        empty = not c.execute("SELECT 1 FROM events").fetchone()
        c.execute("INSERT OR IGNORE INTO lifecycle_clock VALUES(1,?)", (BASE,))
    if empty:
        seed(engine)
    api = FastAPI()

    def clock():
        with connect(path) as c:
            return c.execute("SELECT value FROM lifecycle_clock").fetchone()[0]

    @api.get("/health")
    def health():
        return {"ready": True}

    @api.get("/")
    def page():
        return HTMLResponse((ROOT / "web/lifecycle.html").read_text(encoding="utf8"))

    @api.get("/state")
    def state():
        return engine.tick(clock())

    @api.post("/operate")
    async def operate(request: Request):
        if not secrets.compare_digest(request.headers.get("X-Operator", ""), token):
            raise HTTPException(403)
        if request.headers.get("origin") and request.headers["origin"] != str(request.base_url).rstrip("/"):
            raise HTTPException(403)
        body = await request.json()
        now = clock()
        try:
            op = body["operation"]
            if op == "advance":
                hours = body.get("hours", 1)
                if type(hours) is not int or not 1 <= hours <= 24:
                    raise Refused("clock_step")
                with connect(path) as c:
                    c.execute("UPDATE lifecycle_clock SET value=value+? WHERE id=1", (hours * 3600,))
            elif op == "approve":
                engine.approve(body["id"], body["hash"], now)
            elif op == "hold":
                with connect(path) as c:
                    a = c.execute("SELECT reserved FROM actions WHERE id=?", (body["id"],)).fetchone()
                    if not a or a[0] is not None:
                        raise Refused("reserved_action_requires_reconciliation")
                    c.execute("UPDATE actions SET state='held' WHERE id=?", (body["id"],))
                    engine.log(c, body["id"], now, "operator_hold", {})
            elif op in {"deliver", "lose_ack", "reconcile"}:
                engine.dispatch(body["id"], now, destination, lose_ack=op == "lose_ack")
            elif op in {"revoke", "grant", "convert"}:
                person = body["person"]
                if person not in {f"synthetic-{i:04d}" for i in range(12)}:
                    raise Refused("fixture_person_required")
                with connect(path) as c:
                    f = engine.facts(c, "cedar", person, now)
                kind = "conversion" if op == "convert" else "preference"
                source = "crm" if op == "convert" else "preferences"
                old = f.get(kind)
                revision = (
                    1
                    if not old
                    else next(
                        r["revision"] for r in reversed(self_events(engine)) if r["hash"] == old["_hash"]
                    )
                    + 1
                )
                value = (
                    {"converted": True}
                    if op == "convert"
                    else {"channel": "email", "purpose": "marketing", "allowed": op == "grant"}
                )
                engine.ingest("cedar", person, source, person + "-" + kind, revision, now, now, kind, value)
            else:
                raise Refused("unknown_operation")
        except (Refused, KeyError, ValueError) as e:
            raise HTTPException(409, str(e)) from e
        return engine.tick(clock())

    return api


def self_events(engine):
    with connect(engine.path) as c:
        return [dict(r) for r in c.execute("SELECT * FROM events ORDER BY seq")]
