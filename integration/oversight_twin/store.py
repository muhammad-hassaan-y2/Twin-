"""Durable state for the billing book.

The book's memory is money: which invoice already has an order, which order was captured and by
whom, and which outcome is still unknown. A process restart must not forget any of it, because
forgetting an order is how a client gets charged twice.

Two stores behind one shape. `MemoryStore` is the honest default for tests and demos and says so.
`PostgresStore` writes the same records to a PostgreSQL schema, so a new process reads the book
the old one left. Nothing connects or creates a schema at import: a configured database is
touched on the first billing operation, and if it cannot be reached that operation fails closed
instead of quietly continuing in memory.

The PostgreSQL store is written for a pooled serverless database (Neon and the like). It keeps
no session state: every operation is one short-lived connection running one explicit
transaction, server-side prepared statements are disabled because a transaction pooler may
hand the next statement a different server session, and schema creation is guarded by an
advisory lock that lasts only as long as that transaction.
"""
from __future__ import annotations

import copy
import os
import re
import threading
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Protocol

_SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]{0,40}")
_POSTGRES_DSN = re.compile(r"postgres(ql)?://")


@dataclass(frozen=True)
class BookSnapshot:
    """Everything one merchant's book needs to come back after a restart."""

    invoices: list[dict[str, Any]]
    entries: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    engagements: list[dict[str, Any]]


class StoreUnavailable(RuntimeError):
    """The configured database could not be reached or used. Billing must not pretend otherwise."""


class Store(Protocol):
    def load(self, merchant: str) -> BookSnapshot: ...
    def save_invoice(self, merchant: str, invoice: dict[str, Any]) -> None: ...
    def save_engagement(self, merchant: str, dataset_id: str, key: str,
                        entry: dict[str, Any]) -> None: ...
    def clear_engagements(self, merchant: str, dataset_id: str) -> None: ...
    def save_entry(self, merchant: str, entry: dict[str, Any]) -> None: ...
    def save_conflict(self, merchant: str, entry: dict[str, Any]) -> None: ...
    def describe(self) -> dict[str, Any]: ...


class MemoryStore:
    """Process memory, reset by a restart. Useful for tests, not for a merchant's ledger."""

    def __init__(self) -> None:
        self._invoices: dict[str, dict[str, dict[str, Any]]] = {}
        self._entries: dict[str, dict[str, dict[str, Any]]] = {}
        self._conflicts: dict[str, dict[str, dict[str, Any]]] = {}
        self._engagements: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}

    def load(self, merchant: str) -> BookSnapshot:
        return BookSnapshot(
            invoices=copy.deepcopy(list(self._invoices.get(merchant, {}).values())),
            entries=copy.deepcopy(list(self._entries.get(merchant, {}).values())),
            conflicts=copy.deepcopy(list(self._conflicts.get(merchant, {}).values())),
            engagements=[
                {"dataset_id": dataset, "engagement_key": key, "entry": copy.deepcopy(entry)}
                for (dataset, key), entry in self._engagements.get(merchant, {}).items()
            ],
        )

    def save_invoice(self, merchant: str, invoice: dict[str, Any]) -> None:
        self._invoices.setdefault(merchant, {})[invoice["id"]] = copy.deepcopy(invoice)

    def save_engagement(self, merchant: str, dataset_id: str, key: str,
                        entry: dict[str, Any]) -> None:
        self._engagements.setdefault(merchant, {})[(dataset_id, key)] = copy.deepcopy(entry)

    def clear_engagements(self, merchant: str, dataset_id: str) -> None:
        stored = self._engagements.get(merchant, {})
        for key in [key for key in stored if key[0] == dataset_id]:
            del stored[key]

    def save_entry(self, merchant: str, entry: dict[str, Any]) -> None:
        self._entries.setdefault(merchant, {})[entry["invoice"]["id"]] = copy.deepcopy(entry)

    def save_conflict(self, merchant: str, entry: dict[str, Any]) -> None:
        self._conflicts.setdefault(merchant, {})[entry["invoice"]["id"]] = copy.deepcopy(entry)

    def describe(self) -> dict[str, Any]:
        return {"kind": "memory", "durable": False}


class PostgresStore:
    """The same records in PostgreSQL, one short-lived connection per operation.

    No pool of its own: a connection that serves one transaction cannot hand a half-finished
    transaction to the next request, and on a pooled provider the provider is already the pool.
    """

    def __init__(self, dsn: str, *, schema: str = "oversight",
                 connect_timeout: float = 10.0) -> None:
        if not _POSTGRES_DSN.match(dsn or ""):
            raise ValueError("OVERSIGHT_DATABASE_URL must be a postgresql:// DSN")
        if not _SCHEMA_NAME.fullmatch(schema or ""):
            raise ValueError("the database schema must be a plain lower-case identifier")
        self.dsn = dsn
        self.schema = schema
        self.connect_timeout = connect_timeout
        self._ready = False
        self._lock = threading.Lock()

    def ensure(self) -> None:
        """Create the schema and tables this store needs. Touched only when first used.

        The whole DDL runs in one explicit transaction holding a transaction-scoped advisory
        lock. A session-scoped lock would be wrong here: on a transaction pooler the next
        transaction may run on a different server session, and the lock would sit on a
        connection this process no longer holds. The transaction-scoped lock is released on
        commit, rollback or a dropped connection, so two cold-starting processes cannot race
        `CREATE SCHEMA IF NOT EXISTS` into a duplicate-schema error.
        """
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            sql = self._sql()
            with self._connection(autocommit=False) as conn:
                try:
                    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
                                 (f"oversight-twin:{self.schema}",))
                    conn.execute(sql("CREATE SCHEMA IF NOT EXISTS {schema}"))
                    conn.execute(sql("""
                        CREATE TABLE IF NOT EXISTS {schema}.book_invoices (
                            merchant text NOT NULL,
                            invoice_id text NOT NULL,
                            invoice jsonb NOT NULL,
                            updated_at timestamptz NOT NULL DEFAULT now(),
                            PRIMARY KEY (merchant, invoice_id)
                        )"""))
                    conn.execute(sql("""
                        CREATE TABLE IF NOT EXISTS {schema}.book_entries (
                            merchant text NOT NULL,
                            invoice_id text NOT NULL,
                            state text NOT NULL CHECK (state IN (
                                'awaiting_buyer', 'awaiting_capture', 'captured',
                                'unknown', 'failed')),
                            entry jsonb NOT NULL,
                            updated_at timestamptz NOT NULL DEFAULT now(),
                            PRIMARY KEY (merchant, invoice_id)
                        )"""))
                    conn.execute(sql("""
                        CREATE TABLE IF NOT EXISTS {schema}.book_conflicts (
                            merchant text NOT NULL,
                            invoice_id text NOT NULL,
                            entry jsonb NOT NULL,
                            updated_at timestamptz NOT NULL DEFAULT now(),
                            PRIMARY KEY (merchant, invoice_id)
                        )"""))
                    conn.execute(sql("""
                        CREATE TABLE IF NOT EXISTS {schema}.book_engagements (
                            merchant text NOT NULL,
                            dataset_id text NOT NULL,
                            engagement_key text NOT NULL,
                            entry jsonb NOT NULL,
                            updated_at timestamptz NOT NULL DEFAULT now(),
                            PRIMARY KEY (merchant, dataset_id, engagement_key)
                        )"""))
                    conn.commit()
                except Exception as error:
                    try:
                        conn.rollback()  # also releases the advisory lock
                    except Exception:
                        pass  # a dropped connection releases it server-side
                    _reraise(error)
            self._ready = True

    def load(self, merchant: str) -> BookSnapshot:
        self.ensure()
        invoices = self._query("SELECT invoice FROM {schema}.book_invoices "
                               "WHERE merchant = %s ORDER BY invoice_id", (merchant,))
        entries = self._query("SELECT entry FROM {schema}.book_entries "
                              "WHERE merchant = %s ORDER BY invoice_id", (merchant,))
        conflicts = self._query("SELECT entry FROM {schema}.book_conflicts "
                                "WHERE merchant = %s ORDER BY invoice_id", (merchant,))
        engagements = self._query("SELECT dataset_id, engagement_key, entry "
                                  "FROM {schema}.book_engagements WHERE merchant = %s "
                                  "ORDER BY dataset_id, engagement_key", (merchant,))
        return BookSnapshot(
            invoices=[row[0] for row in invoices],
            entries=[row[0] for row in entries],
            conflicts=[row[0] for row in conflicts],
            engagements=[{"dataset_id": row[0], "engagement_key": row[1], "entry": row[2]}
                         for row in engagements],
        )

    def save_invoice(self, merchant: str, invoice: dict[str, Any]) -> None:
        self._write(
            "INSERT INTO {schema}.book_invoices (merchant, invoice_id, invoice) "
            "VALUES (%s, %s, %s) ON CONFLICT (merchant, invoice_id) DO UPDATE "
            "SET invoice = EXCLUDED.invoice, updated_at = now()",
            (merchant, invoice["id"], _json(invoice)))

    def save_engagement(self, merchant: str, dataset_id: str, key: str,
                        entry: dict[str, Any]) -> None:
        self._write(
            "INSERT INTO {schema}.book_engagements "
            "(merchant, dataset_id, engagement_key, entry) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (merchant, dataset_id, engagement_key) DO UPDATE "
            "SET entry = EXCLUDED.entry, updated_at = now()",
            (merchant, dataset_id, key, _json(entry)))

    def clear_engagements(self, merchant: str, dataset_id: str) -> None:
        self._write("DELETE FROM {schema}.book_engagements "
                    "WHERE merchant = %s AND dataset_id = %s", (merchant, dataset_id))

    def save_entry(self, merchant: str, entry: dict[str, Any]) -> None:
        self._write(
            "INSERT INTO {schema}.book_entries (merchant, invoice_id, state, entry) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (merchant, invoice_id) DO UPDATE "
            "SET state = EXCLUDED.state, entry = EXCLUDED.entry, updated_at = now()",
            (merchant, entry["invoice"]["id"], entry["state"], _json(entry)))

    def save_conflict(self, merchant: str, entry: dict[str, Any]) -> None:
        self._write(
            "INSERT INTO {schema}.book_conflicts (merchant, invoice_id, entry) "
            "VALUES (%s, %s, %s) ON CONFLICT (merchant, invoice_id) DO UPDATE "
            "SET entry = EXCLUDED.entry, updated_at = now()",
            (merchant, entry["invoice"]["id"], _json(entry)))

    def describe(self) -> dict[str, Any]:
        return {"kind": "postgres", "durable": True, "schema": self.schema}

    # --------------------------------------------------------------- internals

    def _sql(self):
        import psycopg
        return lambda text: psycopg.sql.SQL(text).format(
            schema=psycopg.sql.Identifier(self.schema))

    def _connection(self, *, autocommit: bool = True):
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover - depends on the environment
            raise StoreUnavailable(
                "durable state needs psycopg: pip install 'oversight-twin[postgres]'") from error
        try:
            # prepare_threshold=None disables psycopg's automatic server-side prepared
            # statements. A transaction pooler (Neon's -pooler endpoint) can run consecutive
            # transactions of one client on different server sessions, where a prepared
            # statement name that the client believes exists does not. No session state, no
            # "prepared statement does not exist" under load.
            return _Closing(psycopg.connect(self.dsn, autocommit=autocommit,
                                            connect_timeout=self.connect_timeout,
                                            prepare_threshold=None,
                                            application_name="oversight-twin"))
        except psycopg.Error as error:
            raise StoreUnavailable(
                f"the configured database is unreachable ({type(error).__name__})") from error

    def _write(self, statement: str, parameters: tuple[Any, ...]) -> None:
        self.ensure()
        with self._connection() as conn:
            try:
                conn.execute(self._sql()(statement), parameters)
            except Exception as error:
                _reraise(error)

    def _query(self, statement: str, parameters: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        self.ensure()
        with self._connection() as conn:
            try:
                return conn.execute(self._sql()(statement), parameters).fetchall()
            except Exception as error:
                _reraise(error)


class _Closing:
    """Close a psycopg connection on exit; the context manager only ends the transaction."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def __enter__(self) -> Any:
        return self._connection

    def __exit__(self, *exc_info: object) -> None:
        self._connection.close()


def _json(value: dict[str, Any]):
    from psycopg.types.json import Jsonb
    return Jsonb(value)


def _reraise(error: Exception) -> None:
    import psycopg
    if isinstance(error, psycopg.Error):
        raise StoreUnavailable(
            f"the database refused the write ({type(error).__name__}: {error})") from error
    raise error


def store_from_env() -> tuple[Store | None, str]:
    """Memory unless a DSN is configured; a configured DSN that cannot be shaped is refused.

    The database itself is contacted on the first billing operation, not here, so importing the
    application never migrates anything.
    """
    dsn = os.environ.get("OVERSIGHT_DATABASE_URL", "").strip()
    if not dsn:
        return MemoryStore(), ""
    try:
        return PostgresStore(dsn, schema=os.environ.get("OVERSIGHT_DB_SCHEMA", "oversight")), ""
    except ValueError as error:
        return None, str(error)
