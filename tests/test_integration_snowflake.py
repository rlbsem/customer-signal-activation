"""Offline driver-contract tests, not evidence of Snowflake execution."""
import json

import pytest

from signals.integration_snowflake import NativeExecutionError, RecordedConnection, SnowflakeRun


class DriverError(Exception):
    def __init__(self, errno):
        self.errno = errno
        super().__init__("PRIVATE_ACCOUNT PRIVATE_KEY_PATH")


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self.sfqid = None
        self.rows = []
        self.rowcount = 1

    def execute(self, sql, params=None):
        driver = self.connection.driver
        driver.statements.append(sql)
        self.sfqid = f"00000000-0000-0000-0000-{len(driver.statements):012d}"
        if driver.fail_text and driver.fail_text in sql:
            raise DriverError(999)
        result = []
        if sql.startswith("SELECT CURRENT_ROLE"):
            result = [{"role": self.connection.role, "database_name": "REVENUE_METRICS_DEMO", "warehouse_name": "RMP_WH"}]
        elif sql.startswith("SHOW WAREHOUSES"):
            result = [driver.warehouse]
        elif sql.startswith("ALTER WAREHOUSE"):
            driver.warehouse["state"] = "SUSPENDED"
        elif sql.startswith("SHOW GRANTS TO USER"):
            result = [{"role": "RMP_CONSUMER"}]
        elif sql.startswith("SHOW GRANTS ON VIEW"):
            result = [{"privilege": driver.view_privilege, "grantee_name": "RMP_CONSUMER"}]
        elif self.connection.role == "RMP_CONSUMER" and sql.endswith("LIMIT 0"):
            if driver.deny_raw:
                raise DriverError(driver.denial_code)
        if result:
            self.description = [(key,) for key in result[0]]
            self.rows = [tuple(row.values()) for row in result]
        else:
            self.description = None
            self.rows = []
        return self

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self, driver, role):
        self.driver, self.role = driver, role
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


class FakeDriver:
    def __init__(self):
        self.calls = []
        self.connections = []
        self.statements = []
        self.fail_text = None
        self.view_privilege = "SELECT"
        self.deny_raw = True
        self.denial_code = 2003
        self.warehouse = {"name": "RMP_WH", "size": "X-Small", "auto_suspend": 60, "min_cluster_count": 1,
                          "max_cluster_count": 1, "enable_query_acceleration": "false",
                          "resource_monitor": "RMP_FIXTURE_BUDGET", "state": "STARTED"}

    def connect(self, **kwargs):
        self.calls.append(kwargs)
        connection = FakeConnection(self, kwargs["role"])
        self.connections.append(connection)
        return connection


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"SNOWFLAKE_ACCOUNT": "PRIVATE_ACCOUNT", "SNOWFLAKE_USER": "builder",
                               "SNOWFLAKE_PRIVATE_KEY_PATH": "PRIVATE_KEY_PATH",
                               "SNOWFLAKE_CONSUMER_USER": "reader",
                               "SNOWFLAKE_CONSUMER_PRIVATE_KEY_PATH": "PRIVATE_READER_KEY_PATH"}))
    return path


def test_owner_monitor_confirmation_is_required(config):
    with pytest.raises(NativeExecutionError, match="confirmation_required"):
        SnowflakeRun(config)


def test_scope_bounds_cleanup_and_telemetry(config):
    driver = FakeDriver()
    run = SnowflakeRun(config, monitor_owner_confirmed=True, connector=driver)
    with run:
        created = run.schema
        assert run.evidence["warehouse"]["quota_verification"] == "prior_owner_confirmation"
        run.schema = "CSA_INT_" + "A" * 24
    assert f"DROP SCHEMA REVENUE_METRICS_DEMO.{created} CASCADE" in driver.statements
    assert not any(f"DROP SCHEMA REVENUE_METRICS_DEMO.{run.schema}" in sql for sql in driver.statements)
    assert driver.statements[-3:] == ["ALTER WAREHOUSE RMP_WH SUSPEND", "SHOW WAREHOUSES LIKE 'RMP_WH'", "ROLLBACK"]
    assert run.evidence["cleanup"] == {"schema": "dropped", "warehouse": "suspended", "gate": "released"}
    assert all(connection.closed for connection in driver.connections)
    assert all(row["query_id"] and row["statement_sha256"] for row in run.evidence["queries"])
    assert "PRIVATE" not in json.dumps(run.evidence)
    assert driver.calls[0]["session_parameters"]["STATEMENT_TIMEOUT_IN_SECONDS"] == 30
    assert driver.calls[0]["session_parameters"]["LOCK_TIMEOUT"] == 5
    assert "USE SECONDARY ROLES NONE" in driver.statements


@pytest.mark.parametrize("field,value", [("size", "Large"), ("auto_suspend", 0), ("min_cluster_count", 2),
                                        ("max_cluster_count", 2), ("enable_query_acceleration", True),
                                        ("resource_monitor", "OTHER")])
def test_unsafe_warehouse_prevents_schema_creation(config, field, value):
    driver = FakeDriver()
    driver.warehouse[field] = value
    with pytest.raises(NativeExecutionError, match="warehouse_safety_mismatch"):
        with SnowflakeRun(config, monitor_owner_confirmed=True, connector=driver):
            pass
    assert not any(sql.startswith("CREATE") for sql in driver.statements)
    assert not any(sql.startswith("ALTER WAREHOUSE") for sql in driver.statements)


def test_failure_drops_only_created_schema_and_suspends(config):
    driver = FakeDriver()
    driver.fail_text = "CREATE TABLE"
    run = SnowflakeRun(config, monitor_owner_confirmed=True, connector=driver)
    with pytest.raises(NativeExecutionError) as error:
        with run:
            pass
    assert "PRIVATE" not in str(error.value)
    assert run.evidence["cleanup"]["schema"] == "dropped"
    assert run.evidence["cleanup"]["warehouse"] == "suspended"


def test_consumer_readback_and_raw_denial_contract(config):
    driver = FakeDriver()
    run = SnowflakeRun(config, monitor_owner_confirmed=True, connector=driver)
    with run:
        evidence = run.verify_consumer()
        assert evidence["raw_read_denials"] == 3
        assert evidence["write_probe"] == "not_executed"
    grants = [sql for sql in driver.statements if sql.startswith("GRANT")]
    assert len(grants) == 2
    assert not any("TABLE" in sql for sql in grants)
    assert driver.calls[-1]["role"] == "RMP_CONSUMER"


@pytest.mark.parametrize("change", ["raw_allowed", "wrong_error", "write_grant"])
def test_consumer_negative_controls_fail_closed(config, change):
    driver = FakeDriver()
    if change == "raw_allowed":
        driver.deny_raw = False
    elif change == "wrong_error":
        driver.denial_code = 999
    else:
        driver.view_privilege = "OWNERSHIP"
    with SnowflakeRun(config, monitor_owner_confirmed=True, connector=driver) as run:
        with pytest.raises(NativeExecutionError):
            run.verify_consumer()


def test_budget_reserves_cleanup_and_never_exceeds_one_hundred():
    driver = FakeDriver()
    budget = {"used": 93, "cleanup": False}
    recorded = RecordedConnection(FakeConnection(driver, "RMP_BUILD"), [], budget)
    cursor = recorded.cursor()
    cursor.execute("SELECT 1")
    with pytest.raises(NativeExecutionError, match="budget"):
        cursor.execute("SELECT 1")
    budget["cleanup"] = True
    for _ in range(6):
        cursor.execute("SELECT 1")
    with pytest.raises(NativeExecutionError, match="budget"):
        cursor.execute("SELECT 1")
    assert budget["used"] == 100


def test_connection_errors_are_sanitized(tmp_path):
    with pytest.raises(NativeExecutionError) as error:
        with SnowflakeRun(tmp_path / "missing.json", monitor_owner_confirmed=True):
            pass
    assert str(error.value) == "connection_failed; code=2"


def test_hidden_monitor_is_explicit_owner_confirmed_evidence(config):
    driver = FakeDriver()
    driver.warehouse["resource_monitor"] = None
    with SnowflakeRun(config, monitor_owner_confirmed=True, connector=driver) as run:
        assert run.evidence["warehouse"]["monitor_visible"] is False
        assert run.evidence["warehouse"]["monitor_attachment_verification"] == "prior_owner_confirmation"


def test_gate_failure_never_suspends_shared_warehouse(config):
    driver = FakeDriver()
    driver.fail_text = "UPDATE REVENUE_METRICS_DEMO.OPS.ACCEPTANCE_GATE"
    run = SnowflakeRun(config, monitor_owner_confirmed=True, connector=driver)
    with pytest.raises(NativeExecutionError):
        with run:
            pass
    assert not any(sql.startswith("CREATE") or sql.startswith("ALTER WAREHOUSE") for sql in driver.statements)
    assert run.evidence["cleanup"]["warehouse"] == "not_owned_no_suspend"
    assert all(connection.closed for connection in driver.connections)


def test_resource_collection_failure_is_not_a_zero_cost_claim(config):
    driver = FakeDriver()
    with SnowflakeRun(config, monitor_owner_confirmed=True, connector=driver) as run:
        driver.fail_text = "QUERY_HISTORY_BY_SESSION"
        assert run.collect_resource_usage() == {"status": "unavailable", "error_code": 999}
        driver.fail_text = None
