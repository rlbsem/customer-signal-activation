import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .contracts import AUTHORITIES, Event, canonical, digest, now, timestamp


class Refused(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as c:
            c.executescript(Path(__file__).with_name("schema.sql").read_text())
            if c.execute(
                "SELECT 1 FROM events WHERE json_extract(body,'$.schema_version') IS NOT 2 LIMIT 1"
            ).fetchone():
                raise Refused("unsupported_stored_contract: use a fresh v2 workspace")

    @contextmanager
    def tx(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def ingest(self, raw, actor, clock=None):
        e = Event.model_validate(raw)
        if actor != AUTHORITIES[e.kind]:
            raise Refused("source_not_authoritative")
        body = e.model_dump()
        clock = now() if clock is None else clock
        if timestamp(e.occurred_at) > clock + 300:
            raise Refused("future_event")
        if len(canonical(body).encode()) > 8192:
            raise Refused("event_too_large")
        with self.tx() as c:
            old = c.execute(
                "SELECT seq,hash FROM events WHERE brand=? AND event_id=?", (e.brand, e.event_id)
            ).fetchone()
            if old:
                if old["hash"] != digest(body):
                    raise Refused("event_id_payload_conflict")
                return {"seq": old["seq"], "duplicate": True}
            # Entity revision identity cannot be reused through a new transport event ID.
            key_fields = {
                "profile": ["account", "revision"],
                "consent": ["account", "revision"],
                "enrichment": ["account", "provider", "revision"],
                "opportunity": ["opportunity", "revision"],
                "fulfillment": ["fulfillment", "revision"],
                "invoice": ["invoice"],
                "payment": ["allocation"],
                "call": ["call_id"],
                "link": ["session"],
            }.get(e.kind)
            if key_fields:
                for row in c.execute("SELECT body FROM events WHERE brand=? AND kind=?", (e.brand, e.kind)):
                    prev = json.loads(row[0])
                    immutable = {
                        "opportunity": ("opportunity", "account"),
                        "fulfillment": ("fulfillment", "opportunity"),
                    }.get(e.kind)
                    if immutable and prev["data"][immutable[0]] == e.data[immutable[0]]:
                        if prev["data"][immutable[1]] != e.data[immutable[1]]:
                            raise Refused("commercial_entity_reparenting")
                    if all(prev["data"][k] == e.data[k] for k in key_fields):
                        # Reject redundant identities instead of counting an identical call or payment twice.
                        raise Refused("entity_revision_already_recorded")
            cur = c.execute(
                "INSERT INTO events(brand,event_id,kind,occurred,received,body,hash) VALUES(?,?,?,?,?,?,?)",
                (e.brand, e.event_id, e.kind, timestamp(e.occurred_at), clock, canonical(body), digest(body)),
            )
            return {"seq": cur.lastrowid, "duplicate": False}

    def events(self, c, as_of):
        return [
            dict(json.loads(r["body"]), seq=r["seq"], occurred=r["occurred"])
            for r in c.execute("SELECT * FROM events WHERE occurred<=? ORDER BY seq", (as_of,))
        ]

    def status(self):
        with self.tx() as c:
            return {
                "events": c.execute("SELECT count(*) FROM events").fetchone()[0],
                "decisions": c.execute("SELECT count(*) FROM decisions").fetchone()[0],
                "outbox": [
                    dict(r)
                    for r in c.execute(
                        "SELECT destination,state,count(*) AS count FROM outbox GROUP BY destination,state"
                    )
                ],
                "exceptions": [
                    dict(r)
                    for r in c.execute(
                        "SELECT id,state,detail FROM outbox WHERE state IN ('blocked','dead','conflict')"
                    )
                ],
            }
