"""Phase 3A — Neo4j service: configuration, connection, health, unavailable handling. Uses a fake driver (no server)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.services.neo4j_service import (  # noqa: E402
    CONNECTED, NOT_CONFIGURED, UNAVAILABLE, Neo4jQueryError, Neo4jService, Neo4jUnavailable, _safe_uri,
)


class FakeTx:
    def __init__(self, fail=None):
        self.fail = fail
        self.statements = []

    def run(self, cypher, **params):
        self.statements.append((cypher, params))
        if self.fail:
            raise self.fail
        return FakeResult([{"name": "Neo4j Kernel", "version": "5.26.12", "edition": "community"}])


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def data(self):
        return self.rows


class FakeSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute_read(self, work):
        return work(self.driver.tx)

    def execute_write(self, work):
        return work(self.driver.tx)


class FakeDriver:
    instances = []

    def __init__(self, uri, auth=None, connection_timeout=None, fail_connect=None, tx_fail=None):
        self.uri, self.auth, self.connection_timeout = uri, auth, connection_timeout
        self.fail_connect = fail_connect
        self.tx = FakeTx(tx_fail)
        self.closed = False
        self.session_kwargs = None
        FakeDriver.instances.append(self)

    def verify_connectivity(self):
        if self.fail_connect:
            raise self.fail_connect

    def session(self, **kwargs):
        self.session_kwargs = kwargs
        return FakeSession(self)

    def close(self):
        self.closed = True


def factory(**kw):
    return lambda uri, auth=None, connection_timeout=None: FakeDriver(uri, auth, connection_timeout, **kw)


def svc(uri="bolt://localhost:7687", **kw):
    fk = {k: kw.pop(k) for k in ("fail_connect", "tx_fail") if k in kw}
    return Neo4jService(uri, "neo4j", "s3cret-pass", kw.pop("database", "neo4j"), driver_factory=factory(**fk), **kw)


# ------------------------------------------------------------------ configuration
def test_settings_expose_neo4j_variables_with_safe_defaults():
    s = Settings(_env_file=None)
    assert s.NEO4J_URI == "" and s.NEO4J_USER == "neo4j" and s.NEO4J_PASSWORD == "" and s.NEO4J_DATABASE == "neo4j"
    assert s.NEO4J_AUTO_SYNC is True and s.NEO4J_CONNECT_TIMEOUT > 0


def test_from_settings_reads_env(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://graph:7687")
    monkeypatch.setenv("NEO4J_USER", "lineage")
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")
    monkeypatch.setenv("NEO4J_DATABASE", "cases")
    s = Neo4jService.from_settings(Settings(_env_file=None))
    assert (s.uri, s.user, s.database, s.configured) == ("bolt://graph:7687", "lineage", "cases", True)


def test_driver_gets_uri_auth_and_timeout():
    s = svc(connect_timeout=2.5)
    drv = s.driver()
    assert drv.uri == "bolt://localhost:7687" and drv.auth == ("neo4j", "s3cret-pass") and drv.connection_timeout == 2.5
    assert s.driver() is drv                       # reused, not reconnected per call


def test_database_selection_is_passed_to_sessions():
    s = svc(database="cases")
    s.read("RETURN 1")
    assert s._driver.session_kwargs["database"] == "cases"
    s2 = svc(database="")
    s2.read("RETURN 1")
    assert "database" not in s2._driver.session_kwargs   # blank -> server default database


# ------------------------------------------------------------------ health / connection
def test_not_configured_health_and_errors():
    s = Neo4jService("", "neo4j", "", "neo4j")
    h = s.health()
    assert h["status"] == NOT_CONFIGURED and h["configured"] is False and s.is_available() is False
    try:
        s.driver()
        raise AssertionError("expected Neo4jUnavailable")
    except Neo4jUnavailable:
        pass


def test_connected_health_reports_server_without_credentials():
    s = Neo4jService("bolt://neo4j:s3cret-pass@localhost:7687", "neo4j", "s3cret-pass", "neo4j", driver_factory=factory())
    h = s.health()
    assert h["status"] == CONNECTED and h["server"]["version"] == "5.26.12"
    assert "s3cret-pass" not in repr(h) and h["uri"] == "bolt://localhost:7687"


def test_safe_uri_strips_userinfo():
    assert _safe_uri("neo4j+s://u:p@db.example:7687") == "neo4j+s://db.example:7687"
    assert _safe_uri("") is None


def test_unavailable_neo4j_is_reported_and_backs_off():
    FakeDriver.instances.clear()
    s = svc(fail_connect=OSError("Connection refused"), retry_seconds=60)
    h = s.health()
    assert h["status"] == UNAVAILABLE and "Connection refused" in h["error"]
    assert s.is_available() is False
    assert len(FakeDriver.instances) == 1          # second check hit the back-off, no new connection attempt
    assert FakeDriver.instances[0].closed is True
    s.reset_backoff()
    assert s.is_available() is False and len(FakeDriver.instances) == 2


def test_missing_driver_package_is_unavailable(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "neo4j":
            raise ImportError("no neo4j")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    s = Neo4jService("bolt://x:7687", "neo4j", "p", "neo4j")
    h = s.health()
    assert h["status"] == UNAVAILABLE and "not installed" in h["error"]
    try:
        s.reset_backoff()
        s.driver()
        raise AssertionError("expected Neo4jUnavailable")
    except Neo4jUnavailable as e:
        assert "not installed" in str(e)


def test_query_errors_are_distinguished_from_connection_errors():
    s = svc(tx_fail=ValueError("Invalid input 'MATC'"))
    try:
        s.read("MATC (n) RETURN n")
        raise AssertionError("expected Neo4jQueryError")
    except Neo4jQueryError as e:
        assert "Invalid input" in str(e)
    assert s._driver is not None                   # a bad query does not drop the connection


def test_connection_loss_during_query_marks_unavailable():
    s = svc(tx_fail=OSError("socket closed"), retry_seconds=60)
    try:
        s.write("RETURN 1")
        raise AssertionError("expected Neo4jUnavailable")
    except Neo4jUnavailable:
        pass
    assert s._driver is None and s.is_available() is False


def test_transactions_run_all_statements_in_one_unit_of_work():
    s = svc()
    s.write_transaction(lambda tx: [tx.run("CREATE (:A)"), tx.run("CREATE (:B)")])
    assert [c for c, _ in s._driver.tx.statements] == ["CREATE (:A)", "CREATE (:B)"]


def test_close_releases_driver():
    s = svc()
    drv = s.driver()
    s.close()
    assert drv.closed and s._driver is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
