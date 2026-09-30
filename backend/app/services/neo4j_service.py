"""
Neo4j connection service (Phase 3A).

Owns the driver lifecycle, database selection, health checks, transactions and error translation.
It knows nothing about LINEAGE entities — the Cypher lives in app/services/graph_store.py and the
sync/fallback policy in app/services/graph_sync.py.

Availability model
  * NEO4J_URI blank                -> "not_configured" (the app runs exactly as before, in-memory graph)
  * configured but unreachable     -> "unavailable"    (callers fall back to the in-memory graph)
  * reachable                      -> "connected"
After a failed connection the service does not retry for NEO4J_RETRY_SECONDS, so a down Neo4j costs one
short timeout rather than one per request. Credentials are never included in any returned value.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from app.core.config import get_settings

log = logging.getLogger("uvicorn.error")

CONNECTED, UNAVAILABLE, NOT_CONFIGURED = "connected", "unavailable", "not_configured"


class Neo4jUnavailable(RuntimeError):
    """Neo4j is not configured, the driver is missing, or the server cannot be reached."""


class Neo4jQueryError(RuntimeError):
    """Neo4j is reachable but a query/transaction failed (bad Cypher, constraint violation, ...)."""


def _safe_uri(uri: str) -> str | None:
    """scheme://host:port only — strips any user:password@ that someone put in the URI."""
    if not uri:
        return None
    try:
        p = urlsplit(uri)
        host = p.hostname or ""
        return f"{p.scheme}://{host}" + (f":{p.port}" if p.port else "")
    except ValueError:
        return None


class Neo4jService:
    def __init__(
        self, uri: str, user: str, password: str, database: str = "neo4j", *,
        connect_timeout: float = 3.0, retry_seconds: float = 30.0, driver_factory: Callable[..., Any] | None = None,
    ):
        self.uri = (uri or "").strip()
        self.user = user
        self._password = password
        self.database = (database or "").strip() or None   # None -> server default database
        self.connect_timeout = connect_timeout
        self.retry_seconds = retry_seconds
        self._driver_factory = driver_factory
        self._driver = None
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._failed_at: float | None = None
        self._schema_ready = False

    # ------------------------------------------------------------------ config
    @classmethod
    def from_settings(cls, settings=None) -> "Neo4jService":
        s = settings or get_settings()
        return cls(s.NEO4J_URI, s.NEO4J_USER, s.NEO4J_PASSWORD, s.NEO4J_DATABASE,
                   connect_timeout=s.NEO4J_CONNECT_TIMEOUT, retry_seconds=s.NEO4J_RETRY_SECONDS)

    @property
    def configured(self) -> bool:
        return bool(self.uri)

    # ------------------------------------------------------------------ driver lifecycle
    def _make_driver(self):
        if self._driver_factory is not None:
            return self._driver_factory(self.uri, auth=(self.user, self._password),
                                        connection_timeout=self.connect_timeout)
        try:
            from neo4j import GraphDatabase
        except ImportError as e:  # the dependency is optional at runtime
            raise Neo4jUnavailable("The 'neo4j' Python package is not installed.") from e
        return GraphDatabase.driver(
            self.uri, auth=(self.user, self._password),
            connection_timeout=self.connect_timeout, connection_acquisition_timeout=self.connect_timeout * 2,
            max_transaction_retry_time=self.connect_timeout * 2,
        )

    def _mark_failed(self, err: Exception | str) -> None:
        self._last_error = str(err) if str(err) else type(err).__name__
        self._failed_at = time.monotonic()
        self._schema_ready = False
        drv, self._driver = self._driver, None
        if drv is not None:
            try:
                drv.close()
            except Exception:  # noqa: BLE001 — closing a broken driver must never raise
                pass

    def driver(self):
        """Returns a verified driver or raises Neo4jUnavailable. Thread-safe; honours the retry back-off."""
        if not self.configured:
            raise Neo4jUnavailable("NEO4J_URI is not set.")
        with self._lock:
            if self._driver is not None:
                return self._driver
            if self._failed_at is not None and time.monotonic() - self._failed_at < self.retry_seconds:
                raise Neo4jUnavailable(self._last_error or "Neo4j recently failed; waiting before retrying.")
            drv = None
            try:
                drv = self._make_driver()
                drv.verify_connectivity()
            except Exception as e:  # noqa: BLE001 — ServiceUnavailable, AuthError, DNS, missing package ...
                self._driver = drv          # so _mark_failed closes the half-open driver instead of leaking it
                self._mark_failed(e)
                if isinstance(e, Neo4jUnavailable):
                    raise
                raise Neo4jUnavailable(self._last_error) from e
            self._driver, self._last_error, self._failed_at = drv, None, None
            return drv

    def close(self) -> None:
        with self._lock:
            drv, self._driver = self._driver, None
            self._schema_ready = False
        if drv is not None:
            drv.close()

    def reset_backoff(self) -> None:
        """Allow an immediate reconnection attempt (used by explicit sync requests and tests)."""
        with self._lock:
            self._failed_at = None

    # ------------------------------------------------------------------ health
    def is_available(self) -> bool:
        try:
            self.driver()
            return True
        except Neo4jUnavailable:
            return False

    def health(self) -> dict:
        info = {"configured": self.configured, "uri": _safe_uri(self.uri), "database": self.database}
        if not self.configured:
            return {**info, "status": NOT_CONFIGURED, "error": None, "server": None}
        try:
            self.driver()
            rows = self._run(lambda tx: tx.run(
                "CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS version, edition"
            ).data(), write=False)
            server = rows[0] if rows else None
            return {**info, "status": CONNECTED, "error": None, "server": server}
        except (Neo4jUnavailable, Neo4jQueryError) as e:
            return {**info, "status": UNAVAILABLE, "error": str(e), "server": None}

    # ------------------------------------------------------------------ execution
    def _session(self, write: bool):
        drv = self.driver()
        kwargs = {"database": self.database} if self.database else {}
        try:
            from neo4j import READ_ACCESS, WRITE_ACCESS
            kwargs["default_access_mode"] = WRITE_ACCESS if write else READ_ACCESS
        except ImportError:
            pass
        return drv.session(**kwargs)

    def _run(self, work: Callable[[Any], Any], *, write: bool) -> Any:
        """Runs `work(tx)` in a managed (auto-retried) transaction. Connection loss -> Neo4jUnavailable."""
        try:
            with self._session(write) as session:
                return session.execute_write(work) if write else session.execute_read(work)
        except Neo4jUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            if self._is_connection_error(e):
                with self._lock:
                    self._mark_failed(e)
                raise Neo4jUnavailable(str(e)) from e
            raise Neo4jQueryError(f"{type(e).__name__}: {e}") from e

    @staticmethod
    def _is_connection_error(e: Exception) -> bool:
        try:
            from neo4j.exceptions import AuthError, ServiceUnavailable, SessionExpired
            return isinstance(e, (ServiceUnavailable, SessionExpired, AuthError, OSError))
        except ImportError:
            return isinstance(e, OSError)

    def read(self, cypher: str, **params) -> list[dict]:
        return self._run(lambda tx: tx.run(cypher, **params).data(), write=False)

    def write(self, cypher: str, **params) -> list[dict]:
        return self._run(lambda tx: tx.run(cypher, **params).data(), write=True)

    def write_transaction(self, work: Callable[[Any], Any]) -> Any:
        """Several statements in ONE transaction (all-or-nothing). `work` receives the transaction."""
        return self._run(work, write=True)

    def read_transaction(self, work: Callable[[Any], Any]) -> Any:
        return self._run(work, write=False)

    # ------------------------------------------------------------------ schema bookkeeping
    @property
    def schema_ready(self) -> bool:
        return self._schema_ready

    def mark_schema_ready(self) -> None:
        self._schema_ready = True


_service: Neo4jService | None = None
_service_lock = threading.Lock()


def get_neo4j_service() -> Neo4jService:
    global _service
    with _service_lock:
        if _service is None:
            _service = Neo4jService.from_settings()
        return _service


def set_neo4j_service(service: Neo4jService | None) -> None:
    """Swap the process-wide service (tests; or after changing settings)."""
    global _service
    with _service_lock:
        old, _service = _service, service
    if old is not None and old is not service:
        try:
            old.close()
        except Exception:  # noqa: BLE001
            pass


def close_neo4j_service() -> None:
    global _service
    with _service_lock:
        svc, _service = _service, None
    if svc is not None:
        svc.close()
