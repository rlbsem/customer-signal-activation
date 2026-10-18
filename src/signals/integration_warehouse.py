"""Governed review readiness; identical analytical SQL on DuckDB and Snowflake.

The caller selects an isolated schema and serializes writers. Snowflake does not
enforce uniqueness on standard tables: validation is repeated on read, and this
module deliberately does not promise concurrent multi-writer isolation.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SQL_DIRECTORY = Path(__file__).with_name("integration_sql")
ACCOUNT_COLUMNS = (
    "source_ref", "source_modified_at", "brand", "account_key", "owner_key", "owner_ref", "active", "synthetic"
)
REVIEW_COLUMNS = (
    "source_ref", "source_modified_at", "account_source_ref", "action_key", "review_status", "proposed_action"
)
TABLES = {"accounts": ("CSA_ACCOUNTS", ACCOUNT_COLUMNS), "reviews": ("CSA_REVIEWS", REVIEW_COLUMNS)}
HEX = re.compile(r"[0-9a-f]{64}\Z")
KEY = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")


class WarehouseContractError(ValueError):
    """A source batch or stored state is ambiguous or outside the contract."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def utc_timestamp(value):
    if not isinstance(value, str):
        raise WarehouseContractError("timestamp must be a UTC ISO string")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WarehouseContractError("invalid UTC timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise WarehouseContractError("timestamp must explicitly identify UTC")
    return stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate(rows, kind):
    if not isinstance(rows, list):
        raise WarehouseContractError("source collection must be a list")
    columns = TABLES[kind][1]
    result = {}
    for source in rows:
        if not isinstance(source, dict) or set(source) != set(columns):
            raise WarehouseContractError(f"{kind}: unexpected or missing fields")
        row = dict(source)
        row["source_modified_at"] = utc_timestamp(row["source_modified_at"])
        for name, value in row.items():
            if name in ("active", "synthetic"):
                if type(value) is not bool:
                    raise WarehouseContractError(f"{name} must be boolean")
            elif not isinstance(value, str) or not value:
                raise WarehouseContractError(f"{name} must be a nonempty string")
            elif name.endswith("_ref") or name == "action_key":
                if not HEX.fullmatch(value):
                    raise WarehouseContractError(f"{name} must be a lowercase SHA256")
            elif name in ("brand", "owner_key") and not KEY.fullmatch(value):
                raise WarehouseContractError(f"{name} is not canonical")
            elif name == "account_key" and not re.fullmatch(r"account-[0-9]{4,}", value):
                raise WarehouseContractError("account_key is not canonical")
        if kind == "reviews":
            if row["review_status"] not in {"Pending", "Reviewed", "Rejected"}:
                raise WarehouseContractError("unknown review status")
            if row["proposed_action"] not in {"schedule_discovery", "clarify_need", "support_handoff"}:
                raise WarehouseContractError("unknown proposed action")
        version = (row["source_ref"], row["source_modified_at"])
        if version in result and result[version] != row:
            raise WarehouseContractError("conflicting same-version source content")
        result[version] = row
    return [result[key] for key in sorted(result)]


def _latest(rows):
    latest = {}
    for row in sorted(rows, key=lambda row: row["source_modified_at"]):
        latest[row["source_ref"]] = row
    return sorted(latest.values(), key=lambda row: row["source_ref"])


def _coherent(accounts, reviews):
    known = {row["source_ref"] for row in accounts}
    mapping = {}
    owner_mapping = {}
    for row in _latest(accounts):
        key = (row["brand"], row["account_key"])
        if key in mapping and mapping[key] != row["source_ref"]:
            raise WarehouseContractError("ambiguous current account mapping")
        mapping[key] = row["source_ref"]
        owner_key = (row["brand"], row["owner_key"])
        if owner_key in owner_mapping and owner_mapping[owner_key] != row["owner_ref"]:
            raise WarehouseContractError("ambiguous current owner mapping")
        owner_mapping[owner_key] = row["owner_ref"]
    actions = {}
    review_identity = {}
    for row in reviews:
        if row["account_source_ref"] not in known:
            raise WarehouseContractError("review references an unknown account")
        identity = (row["account_source_ref"], row["action_key"], row["proposed_action"])
        if row["source_ref"] in review_identity and review_identity[row["source_ref"]] != identity:
            raise WarehouseContractError("immutable review identity changed")
        review_identity[row["source_ref"]] = identity
        if row["action_key"] in actions and actions[row["action_key"]] != row["source_ref"]:
            raise WarehouseContractError("action key identifies multiple reviews")
        actions[row["action_key"]] = row["source_ref"]


def _query(connection, sql, params=None):
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params) if params is not None else cursor.execute(sql)
        if cursor.description is None:
            return []
        names = [column[0].lower() for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def initialize(connection):
    """Create only CSA tables in the caller-selected isolated database/schema."""
    for statement in (SQL_DIRECTORY / "schema.sql").read_text(encoding="utf-8").split(";"):
        if statement.strip():
            _query(connection, statement)


def source_rows(connection):
    """Return complete business-version history; no run metadata is mixed in."""
    rows = {}
    for kind, (table, columns) in TABLES.items():
        stored = _query(connection, f"SELECT {', '.join(columns)} FROM {table}")
        rows[kind] = _validate(stored, kind)
        if len(stored) != len(rows[kind]):
            raise WarehouseContractError("duplicate stored source versions")
    _coherent(rows["accounts"], rows["reviews"])
    return rows


def load(connection, accounts, reviews, *, run_id=None, observed_at=None, placeholder="?"):
    """Append versions atomically. Replayed content is a no-op; old versions cannot regress decisions.

    Use placeholder='%s' for the Snowflake connector. Supply a dedicated connection
    with no active caller transaction. DDL initialization is deliberately separate.
    """
    if placeholder not in {"?", "%s"}:
        raise ValueError("unsupported DBAPI placeholder")
    batch = {"accounts": _validate(accounts, "accounts"), "reviews": _validate(reviews, "reviews")}
    run_id = run_id or str(uuid4())
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise WarehouseContractError("invalid ingestion run ID")
    observed_at = utc_timestamp(observed_at or datetime.now(timezone.utc).isoformat())
    input_hash = digest(batch)
    cursor = connection.cursor()
    try:
        cursor.execute("BEGIN TRANSACTION")
        existing = source_rows(connection)
        merged = {kind: _validate(existing[kind] + batch[kind], kind) for kind in TABLES}
        _coherent(merged["accounts"], merged["reviews"])
        previous = _query(connection, f"SELECT input_hash FROM CSA_INGESTION WHERE run_id = {placeholder}", (run_id,))
        if previous and any(row["input_hash"] != input_hash for row in previous):
            raise WarehouseContractError("run ID reused for different input")
        inserted = {}
        for kind, (table, columns) in TABLES.items():
            old = {(row["source_ref"], row["source_modified_at"]) for row in existing[kind]}
            additions = [row for row in batch[kind] if (row["source_ref"], row["source_modified_at"]) not in old]
            inserted[kind] = len(additions)
            for row in additions:
                cursor.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join([placeholder] * len(columns))})",
                               tuple(row[column] for column in columns))
        if not previous:
            cursor.execute(f"INSERT INTO CSA_INGESTION VALUES ({', '.join([placeholder] * 5)})",
                           (run_id, observed_at, input_hash, len(batch["accounts"]), len(batch["reviews"])))
        cursor.execute("COMMIT")
    except Exception:
        cursor.execute("ROLLBACK")
        raise
    finally:
        cursor.close()
    return {"run_id": run_id, "observed_at": observed_at, "input_hash": input_hash, "inserted": inserted}


def decisions(connection):
    """Return readiness proposals only, with hashes independent of ingestion order/time."""
    sources = source_rows(connection)
    accounts = {row["source_ref"]: row for row in _latest(sources["accounts"])}
    reviews = _latest(sources["reviews"])
    rows = _query(connection, (SQL_DIRECTORY / "decisions.sql").read_text(encoding="utf-8"))
    for row in rows:
        for name in ("review_count", "pending_count", "reviewed_count", "rejected_count"):
            row[name] = int(row[name])
        row["source_hash"] = digest({"account": accounts[row["account_source_ref"]],
                                     "reviews": [review for review in reviews
                                                 if review["account_source_ref"] == row["account_source_ref"]]})
        row["decision_hash"] = digest(row)
    return rows


class LocalWarehouse:
    def __init__(self, path=":memory:"):
        import duckdb
        self.connection = duckdb.connect(str(path))
        initialize(self.connection)

    def load(self, accounts, reviews, **kwargs):
        return load(self.connection, accounts, reviews, **kwargs)

    def decisions(self):
        return decisions(self.connection)

    def source_rows(self):
        return source_rows(self.connection)

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
