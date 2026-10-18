"""Bounded native execution in a uniquely owned, disposable demo schema.

Requires optional snowflake-connector-python==3.18.1 and cryptography==46.0.0.
No provisioning, credential discovery, retries, or account-admin operations.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from uuid import uuid4

from . import integration_warehouse as warehouse

DATABASE = "REVENUE_METRICS_DEMO"
WAREHOUSE = "RMP_WH"
MONITOR = "RMP_FIXTURE_BUDGET"
SCHEMA_PATTERN = re.compile(r"CSA_INT_[0-9A-F]{24}\Z")


class NativeExecutionError(RuntimeError):
    """Public-safe error; never incorporates vendor messages or private config."""

    def __init__(self, stage, errno=None):
        self.stage = stage
        self.errno = errno if type(errno) is int else None
        super().__init__(f"{stage}; code={self.errno if self.errno is not None else 'unavailable'}")


class RecordedCursor:
    def __init__(self, connection):
        self.connection = connection
        self.raw = connection.raw.cursor()

    @property
    def description(self):
        return self.raw.description

    @property
    def rowcount(self):
        return self.raw.rowcount

    def execute(self, sql, params=None):
        budget = self.connection.budget
        limit = 100 if budget["cleanup"] else 94
        if budget["used"] >= limit:
            raise NativeExecutionError("query_budget_exhausted")
        budget["used"] += 1
        start = time.monotonic()
        record = {"statement_sha256": hashlib.sha256(sql.encode()).hexdigest(), "status": "failed"}
        try:
            self.raw.execute(sql, params) if params is not None else self.raw.execute(sql)
            record["status"] = "succeeded"
            return self
        except Exception as exc:
            record["error_code"] = getattr(exc, "errno", None) if type(getattr(exc, "errno", None)) is int else None
            raise NativeExecutionError("query_failed", record["error_code"]) from None
        finally:
            query_id = getattr(self.raw, "sfqid", None)
            record["query_id"] = query_id if isinstance(query_id, str) and re.fullmatch(r"[0-9a-fA-F-]{20,80}", query_id) else None
            record["client_elapsed_ms"] = round((time.monotonic() - start) * 1000, 3)
            self.connection.records.append(record)

    def fetchall(self):
        try:
            return self.raw.fetchall()
        except Exception as exc:
            raise NativeExecutionError("fetch_failed", getattr(exc, "errno", None)) from None

    def close(self):
        try:
            self.raw.close()
        except Exception as exc:
            raise NativeExecutionError("cursor_close_failed", getattr(exc, "errno", None)) from None


class RecordedConnection:
    def __init__(self, raw, records, budget):
        self.raw, self.records, self.budget = raw, records, budget

    def cursor(self):
        return RecordedCursor(self)

    def close(self):
        try:
            self.raw.close()
        except Exception as exc:
            raise NativeExecutionError("connection_close_failed", getattr(exc, "errno", None)) from None


class SnowflakeRun:
    """Use `with SnowflakeRun(path, monitor_owner_confirmed=True) as run`.

    run.connection supports integration_warehouse's functions (%s parameters).
    run.load / run.decisions wrap them. run.verify_consumer grants only schema
    USAGE and SELECT on a candidate view, then checks distinct consumer identity.
    `evidence` remains accessible after cleanup. Never store this object publicly.
    """
    def __init__(self, config_path, *, monitor_owner_confirmed=False, connector=None):
        if monitor_owner_confirmed is not True:
            raise NativeExecutionError("one_credit_monitor_owner_confirmation_required")
        self.config_path = Path(config_path)
        self.connector = connector
        self.schema = "CSA_INT_" + uuid4().hex[:24].upper()
        self.connection = None
        self.gate_connection = None
        self.gate_acquired = False
        self.created = False
        self._created_schema = None
        self.budget = {"used": 0, "cleanup": False}
        self.evidence = {"queries": [], "warehouse": None, "consumer": "not_run", "cleanup": "not_run",
                         "resources": {"status": "not_collected"}, "exclusive_gate": "not_acquired"}

    def _connect(self, consumer=False):
        connection = None
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            prefix = "SNOWFLAKE_CONSUMER_" if consumer else "SNOWFLAKE_"
            if consumer and config[prefix + "USER"].upper() == config["SNOWFLAKE_USER"].upper():
                raise NativeExecutionError("distinct_consumer_identity_required")
            connector = self.connector
            if connector is None:
                import snowflake.connector as connector
            raw = connector.connect(
                account=config["SNOWFLAKE_ACCOUNT"], user=config[prefix + "USER"],
                private_key_file=config[prefix + "PRIVATE_KEY_PATH"],
                private_key_file_pwd=config.get(prefix + "PRIVATE_KEY_PASSPHRASE") or None,
                role="RMP_CONSUMER" if consumer else "RMP_BUILD", database=DATABASE, warehouse=WAREHOUSE,
                login_timeout=20, network_timeout=30, client_session_keep_alive=False,
                session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": 30, "LOCK_TIMEOUT": 5,
                                    "QUERY_TAG": "csa_connected_acceptance", "USE_CACHED_RESULT": False},
            )
            connection = RecordedConnection(raw, self.evidence["queries"], self.budget)
            warehouse._query(connection, "USE SECONDARY ROLES NONE")
            identity = warehouse._query(connection, "SELECT CURRENT_ROLE() AS role, CURRENT_DATABASE() AS database_name, "
                                       "CURRENT_WAREHOUSE() AS warehouse_name")
            expected = {"role": "RMP_CONSUMER" if consumer else "RMP_BUILD", "database_name": DATABASE,
                        "warehouse_name": WAREHOUSE}
            if identity != [expected]:
                raise NativeExecutionError("session_identity_mismatch")
            if consumer:
                user = config[prefix + "USER"]
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", user):
                    raise NativeExecutionError("unsupported_consumer_identifier")
                grants = warehouse._query(connection, f'SHOW GRANTS TO USER "{user.upper()}"')
                roles = {row.get("role") for row in grants}
                if not roles or roles - {"PUBLIC", "RMP_CONSUMER"} or "RMP_CONSUMER" not in roles:
                    raise NativeExecutionError("consumer_extra_role_grants")
                inherited = warehouse._query(connection, "SHOW GRANTS TO ROLE RMP_CONSUMER")
                if any(row.get("granted_on") == "ROLE" for row in inherited):
                    raise NativeExecutionError("consumer_inherited_role_grants")
            return connection
        except NativeExecutionError:
            if connection:
                connection.close()
            raise
        except Exception as exc:
            if connection:
                connection.close()
            raise NativeExecutionError("connection_failed", getattr(exc, "errno", None)) from None

    def __enter__(self):
        try:
            self.connection = self._connect()
            rows = warehouse._query(self.connection, "SHOW WAREHOUSES LIKE 'RMP_WH'")
            rows = [row for row in rows if row.get("name") == WAREHOUSE]
            if len(rows) != 1:
                raise NativeExecutionError("warehouse_not_visible")
            row = rows[0]
            monitor = row.get("resource_monitor")
            monitor_visible = monitor not in (None, "", "null", "NULL")
            if (str(row.get("size")).upper().replace("-", "") != "XSMALL"
                    or int(row.get("auto_suspend", -1)) != 60
                    or int(row.get("min_cluster_count", -1)) != 1
                    or int(row.get("max_cluster_count", -1)) != 1
                    or str(row.get("enable_query_acceleration")).lower() != "false"
                    or (monitor_visible and monitor != MONITOR)):
                raise NativeExecutionError("warehouse_safety_mismatch")
            self.evidence["warehouse"] = {"size": "XSMALL", "auto_suspend_seconds": 60, "max_clusters": 1,
                                          "query_acceleration": False, "monitor_visible": monitor_visible,
                                          "monitor_attachment_verification": "runtime_visible" if monitor_visible else "prior_owner_confirmation",
                                          "credit_quota": 1, "quota_verification": "prior_owner_confirmation"}
            if not SCHEMA_PATTERN.fullmatch(self.schema):
                raise NativeExecutionError("unsafe_schema_name")
            self.gate_connection = self._connect()
            warehouse._query(self.gate_connection, "BEGIN")
            gate = self.gate_connection.cursor()
            try:
                gate.execute("UPDATE REVENUE_METRICS_DEMO.OPS.ACCEPTANCE_GATE SET holder='running' WHERE singleton=1")
                if gate.rowcount != 1:
                    raise NativeExecutionError("exclusive_gate_row_count")
                self.gate_acquired = True
                self.evidence["exclusive_gate"] = "acquired"
            finally:
                gate.close()
            warehouse._query(self.connection, f"CREATE TRANSIENT SCHEMA {DATABASE}.{self.schema} DATA_RETENTION_TIME_IN_DAYS=0")
            self.created = True
            self._created_schema = self.schema
            warehouse._query(self.connection, f"USE SCHEMA {DATABASE}.{self.schema}")
            warehouse.initialize(self.connection)
            return self
        except Exception:
            self._cleanup()
            raise

    def load(self, accounts, reviews, **kwargs):
        return warehouse.load(self.connection, accounts, reviews, placeholder="%s", **kwargs)

    def decisions(self):
        return warehouse.decisions(self.connection)

    def source_rows(self):
        return warehouse.source_rows(self.connection)

    def verify_consumer(self):
        if not self.created or self.schema != self._created_schema or not SCHEMA_PATTERN.fullmatch(self.schema):
            raise NativeExecutionError("owned_schema_required")
        namespace = f"{DATABASE}.{self.schema}"
        query = (warehouse.SQL_DIRECTORY / "decisions.sql").read_text(encoding="utf-8")
        warehouse._query(self.connection, f"CREATE VIEW {namespace}.CSA_CANDIDATE AS {query}")
        warehouse._query(self.connection, f"GRANT USAGE ON SCHEMA {namespace} TO ROLE RMP_CONSUMER")
        warehouse._query(self.connection, f"GRANT SELECT ON VIEW {namespace}.CSA_CANDIDATE TO ROLE RMP_CONSUMER")
        grants = warehouse._query(self.connection, f"SHOW GRANTS ON VIEW {namespace}.CSA_CANDIDATE")
        effective = {row["privilege"] for row in grants if row.get("grantee_name") == "RMP_CONSUMER"}
        if effective != {"SELECT"}:
            raise NativeExecutionError("consumer_view_grants_unexpected")
        consumer = self._connect(consumer=True)
        try:
            actual = warehouse._query(consumer, f"SELECT * FROM {namespace}.CSA_CANDIDATE ORDER BY brand, account_key, account_source_ref")
            expected = warehouse._query(self.connection, query)
            if actual != expected:
                raise NativeExecutionError("consumer_readback_mismatch")
            for table in ("CSA_ACCOUNTS", "CSA_REVIEWS", "CSA_INGESTION"):
                try:
                    warehouse._query(consumer, f"SELECT * FROM {namespace}.{table} LIMIT 0")
                except NativeExecutionError as exc:
                    if exc.errno != 2003:
                        raise NativeExecutionError("raw_denial_not_established", exc.errno) from None
                else:
                    raise NativeExecutionError("consumer_raw_access_unexpected")
            self.evidence["consumer"] = {"candidate_readback": "passed", "raw_read_denials": 3,
                                         "view_grants": ["SELECT"], "write_probe": "not_executed",
                                         "write_boundary": "read_only_grant_inspection",
                                         "separate_identity": True, "user_role_grants_checked": True,
                                         "cryptographic_key_distinctness": "not_verified"}
            return self.evidence["consumer"]
        finally:
            consumer.close()

    def collect_resource_usage(self):
        """Bounded builder-session counters, not final warehouse monetary cost."""
        try:
            rows = warehouse._query(self.connection,
                "SELECT query_id, execution_status, total_elapsed_time, bytes_scanned, "
                "credits_used_cloud_services FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION(RESULT_LIMIT=>100))")
            ids = {row["query_id"] for row in self.evidence["queries"] if row["query_id"]}
            selected = [{"query_id": row["query_id"], "execution_status": row["execution_status"],
                         "elapsed_ms": int(row["total_elapsed_time"]),
                         "bytes_scanned": int(row['bytes_scanned']) if row['bytes_scanned'] is not None else None,
                         "cloud_service_credits": float(row['credits_used_cloud_services'])
                         if row['credits_used_cloud_services'] is not None else None}
                        for row in rows if row["query_id"] in ids and row['execution_status'] == 'SUCCESS'
                        and row['total_elapsed_time'] is not None and row['total_elapsed_time'] >= 0]
            self.evidence["resources"] = {"status": "collected" if selected else "not_visible_yet",
                                           "scope": "builder_session_before_cleanup",
                                           "not_total_warehouse_cost": True, "queries": selected,
                                           "completed_successful_rows": len(selected),
                                           "bytes_scanned": sum(row["bytes_scanned"] for row in selected
                                                                if row['bytes_scanned'] is not None),
                                           "elapsed_ms": sum(row["elapsed_ms"] for row in selected),
                                           "cloud_service_credits": sum(row["cloud_service_credits"] for row in selected
                                                                         if row['cloud_service_credits'] is not None)}
        except NativeExecutionError as exc:
            self.evidence["resources"] = {"status": "unavailable", "error_code": exc.errno}
        return self.evidence["resources"]

    def _cleanup(self):
        if self.connection is None:
            return
        self.budget["cleanup"] = True
        result = {"schema": "not_created", "warehouse": "not_suspended"}
        try:
            if self.created and self._created_schema and SCHEMA_PATTERN.fullmatch(self._created_schema):
                warehouse._query(self.connection, f"DROP SCHEMA {DATABASE}.{self._created_schema} CASCADE")
                result["schema"] = "dropped"
                self.created = False
        except NativeExecutionError as exc:
            result["schema"] = "cleanup_failed"
            result["schema_error_code"] = exc.errno
        finally:
            try:
                if not self.gate_acquired:
                    result["warehouse"] = "not_owned_no_suspend"
                    return
                rows = warehouse._query(self.connection, "SHOW WAREHOUSES LIKE 'RMP_WH'")
                matched = [row for row in rows if row.get("name") == WAREHOUSE]
                if len(matched) == 1 and matched[0].get("state") == "SUSPENDED":
                    result["warehouse"] = "already_suspended"
                else:
                    warehouse._query(self.connection, "ALTER WAREHOUSE RMP_WH SUSPEND")
                    after = warehouse._query(self.connection, "SHOW WAREHOUSES LIKE 'RMP_WH'")
                    if not any(row.get("name") == WAREHOUSE and row.get("state") == "SUSPENDED" for row in after):
                        raise NativeExecutionError("suspension_not_confirmed")
                    result["warehouse"] = "suspended"
            except NativeExecutionError as exc:
                result["warehouse"] = "suspend_failed"
                result["warehouse_error_code"] = exc.errno
            finally:
                if self.gate_connection:
                    try:
                        warehouse._query(self.gate_connection, "ROLLBACK")
                        result["gate"] = "released"
                    except NativeExecutionError as exc:
                        result["gate"] = "rollback_failed_connection_closed"
                        result["gate_error_code"] = exc.errno
                    finally:
                        self.gate_connection.close()
                        self.gate_connection = None
                        self.gate_acquired = False
                self.evidence["cleanup"] = result
                try:
                    self.connection.close()
                finally:
                    self.connection = None

    def __exit__(self, *args):
        self._cleanup()
