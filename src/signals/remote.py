"""Separate durable HTTP destination with CRM-owned fields and fault injection."""

import json
import sqlite3
import time
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request

from .contracts import canonical, digest


@contextmanager
def connect(path):
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def initialize(path):
    with connect(path) as c:
        c.executescript("""CREATE TABLE IF NOT EXISTS contacts(id TEXT PRIMARY KEY,revision INTEGER,body TEXT);
          CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,hash TEXT,body TEXT);
          CREATE TABLE IF NOT EXISTS conversions(id TEXT PRIMARY KEY,body TEXT);
          CREATE TABLE IF NOT EXISTS faults(id TEXT PRIMARY KEY,mode TEXT);""")


def app(path):
    initialize(path)
    api = FastAPI(title="Local CRM and conversion destination")

    @api.get("/health")
    def health():
        return {"ready": True}

    @api.get("/receipts/{key}")
    def receipt(key: str):
        with connect(path) as c:
            row = c.execute("SELECT body FROM receipts WHERE id=?", (key,)).fetchone()
            if not row:
                raise HTTPException(404)
            return json.loads(row[0])

    @api.get("/contacts/{key}")
    def contact(key: str):
        with connect(path) as c:
            row = c.execute("SELECT * FROM contacts WHERE id=?", (key,)).fetchone()
            return (
                {"revision": row["revision"], "properties": json.loads(row["body"])}
                if row
                else {"revision": 0, "properties": {}}
            )

    @api.get("/conversions/{key}")
    def conversion(key: str):
        with connect(path) as c:
            row = c.execute("SELECT body FROM conversions WHERE id=?", (key,)).fetchone()
            if not row:
                raise HTTPException(404)
            return json.loads(row[0])

    @api.post("/apply/{destination}/{key}")
    async def apply(destination: str, key: str, request: Request):
        if destination not in ("crm", "conversion"):
            raise HTTPException(404)
        body = await request.json()
        payload = body["payload"]
        mode = None
        # Fault consumption commits independently of the business transaction.
        with connect(path) as c:
            fault = c.execute("SELECT mode FROM faults WHERE id=?", (key,)).fetchone()
            if fault:
                mode = fault[0]
                c.execute("DELETE FROM faults WHERE id=?", (key,))
        if mode == "rate_limit":
            raise HTTPException(429, headers={"Retry-After": "2"})
        if mode == "unavailable":
            raise HTTPException(503)
        with connect(path) as c:
            old = c.execute("SELECT * FROM receipts WHERE id=?", (key,)).fetchone()
            if old:
                if old["hash"] != digest(payload):
                    raise HTTPException(409, "idempotency payload conflict")
                return json.loads(old["body"])
            if destination == "crm":
                allowed = {"external_id", "score", "owner", "lifecycle", "campaign", "decision_id"}
                if set(payload) != allowed:
                    raise HTTPException(422, "unowned or missing field")
                row = c.execute("SELECT * FROM contacts WHERE id=?", (payload["external_id"],)).fetchone()
                revision = row["revision"] if row else 0
                properties = json.loads(row["body"]) if row else {}
                if revision != body["expected_revision"]:
                    raise HTTPException(409, "stale remote revision")
                if properties.get("owner") and properties["owner"] != payload["owner"]:
                    raise HTTPException(409, "sales-owned owner conflict")
                # Unrelated remote fields (e.g. sales_note) survive projection updates.
                properties.update(payload)
                c.execute(
                    "INSERT OR REPLACE INTO contacts VALUES(?,?,?)",
                    (payload["external_id"], revision + 1, canonical(properties)),
                )
            else:
                if set(payload) != {
                    "order_id",
                    "gclid",
                    "conversion_time",
                    "value_cents",
                    "currency",
                    "account",
                    "brand",
                    "invoice",
                    "touch_id",
                }:
                    raise HTTPException(422, "invalid conversion contract")
                existing = c.execute(
                    "SELECT body FROM conversions WHERE id=?", (payload["order_id"],)
                ).fetchone()
                if existing and existing[0] != canonical(payload):
                    raise HTTPException(409, "conversion correction requires review")
                c.execute(
                    "INSERT OR IGNORE INTO conversions VALUES(?,?)", (payload["order_id"], canonical(payload))
                )
            receipt = {"id": key, "destination": destination, "payload_hash": digest(payload)}
            c.execute("INSERT INTO receipts VALUES(?,?,?)", (key, digest(payload), canonical(receipt)))
        if mode == "timeout_after_commit":
            time.sleep(0.5)
        return receipt

    return api
