"""Independent durable acceptance emulator. No email transport or vendor integration."""

import json
from fastapi import FastAPI, HTTPException, Request
from .contracts import canonical, digest
from .remote import connect


def app(path):
    with connect(path) as c:
        c.executescript(
            "CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,body TEXT); CREATE TABLE IF NOT EXISTS faults(id TEXT PRIMARY KEY,mode TEXT);"
        )
    api = FastAPI()

    @api.get("/health")
    def health():
        return {"ready": True}

    @api.get("/receipts/{key}")
    def receipt(key: str):
        with connect(path) as c:
            r = c.execute("SELECT body FROM receipts WHERE id=?", (key,)).fetchone()
            if not r:
                raise HTTPException(404)
            return json.loads(r[0])

    @api.post("/accept/{key}")
    async def accept(key: str, request: Request):
        body = await request.json()
        if set(body) != {"brand", "person", "journey", "version", "channel", "purpose", "text"} or not body[
            "person"
        ].startswith("synthetic-"):
            raise HTTPException(422)
        with connect(path) as c:
            fault = c.execute("SELECT mode FROM faults WHERE id=?", (key,)).fetchone()
            if fault:
                raise HTTPException(429 if fault[0] == "rate_limit" else 503)
            r = c.execute("SELECT body FROM receipts WHERE id=?", (key,)).fetchone()
            if r:
                old = json.loads(r[0])
                if old["payload_hash"] != digest(body):
                    raise HTTPException(409)
                return old
            value = {"id": key, "payload_hash": digest(body), "accepted": True}
            c.execute("INSERT INTO receipts VALUES(?,?)", (key, canonical(value)))
            return value

    return api
