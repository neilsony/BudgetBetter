"""The SQLite connection, the schema, and the tables every domain shares.

Spending tables live in `budgetbetter.budgeting.db`, investing tables in
`budgetbetter.investing.db`, the shared ledger in `budgetbetter.household.db`.
See ADR-0001, ADR-0012 and ADR-0018.
"""

import datetime as dt
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from budgetbetter.core.models import Account

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# Each domain owns its own tables. Listed as paths rather than imported, so
# core stays free of any dependency on the domains built on top of it.
SCHEMA_PATHS = (
    PACKAGE_ROOT / "core" / "schema.sql",
    PACKAGE_ROOT / "budgeting" / "schema.sql",
    PACKAGE_ROOT / "investing" / "schema.sql",
    PACKAGE_ROOT / "household" / "schema.sql",
)


def connect(database: str | Path) -> sqlite3.Connection:
    # One connection per request, never shared concurrently — but FastAPI may run
    # the dependency that opens it and the endpoint that uses it on different
    # threadpool workers, which SQLite otherwise refuses.
    connection = sqlite3.connect(database, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    # Off by default in SQLite, which would make every ON DELETE CASCADE in the
    # schema decorative and let orphan rows through. A no-op inside a
    # transaction, so it has to happen here. See ADR-0018.
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def writing(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """A write transaction that takes the write lock up front.

    Python opens transactions DEFERRED: they begin as a read and upgrade on the
    first write. In WAL mode, if another connection wrote in between, SQLite
    returns SQLITE_BUSY_SNAPSHOT and deliberately refuses to retry, because
    retrying could deadlock — a busy timeout cannot rescue it. Every
    read-modify-write goes through here instead. See ADR-0018.
    """
    if connection.in_transaction:
        connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    connection.commit()


def initialise(connection: sqlite3.Connection) -> None:
    """Create every domain's schema, and seed the Rules table if it is empty."""
    for schema_path in SCHEMA_PATHS:
        connection.executescript(schema_path.read_text())
    _migrate(connection)
    connection.commit()

    already_seeded = connection.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
    if not already_seeded:
        # Imported here rather than at module scope: core must not depend on
        # the domains layered above it.
        from budgetbetter.budgeting import db as budgeting_db
        from budgetbetter.budgeting.buckets import SEED_RULES

        budgeting_db.replace_rules(connection, SEED_RULES)


def _migrate(connection: sqlite3.Connection) -> None:
    """Add columns that CREATE TABLE IF NOT EXISTS cannot add to an existing table."""
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(items)")}
    if "kind" not in columns:
        connection.execute(
            "ALTER TABLE items ADD COLUMN kind TEXT NOT NULL DEFAULT 'budgeting'"
        )

    columns = {row["name"] for row in connection.execute("PRAGMA table_info(securities)")}
    if columns and "close_price_as_of" not in columns:
        connection.execute("ALTER TABLE securities ADD COLUMN close_price_as_of TEXT")

    columns = {row["name"] for row in connection.execute("PRAGMA table_info(accounts)")}
    if columns and "current_balance" not in columns:
        connection.execute("ALTER TABLE accounts ADD COLUMN current_balance REAL")


# --- Items -----------------------------------------------------------------


def upsert_item(
    connection: sqlite3.Connection,
    *,
    item_id: str,
    institution_id: str | None,
    institution_name: str | None,
    access_token_encrypted: str,
    kind: str = "budgeting",
) -> None:
    connection.execute(
        """
        INSERT INTO items (item_id, institution_id, institution_name,
                           access_token_encrypted, created_at, kind)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (item_id) DO UPDATE SET
            institution_id         = excluded.institution_id,
            institution_name       = excluded.institution_name,
            access_token_encrypted = excluded.access_token_encrypted,
            kind                   = excluded.kind
        """,
        (
            item_id,
            institution_id,
            institution_name,
            access_token_encrypted,
            dt.datetime.now().isoformat(timespec="seconds"),
            kind,
        ),
    )
    connection.commit()


def get_item(connection: sqlite3.Connection, item_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM items WHERE item_id = ?", (item_id,)).fetchone()


def list_items(connection: sqlite3.Connection, *, kind: str | None = None) -> list[sqlite3.Row]:
    if kind:
        return connection.execute(
            "SELECT * FROM items WHERE kind = ? ORDER BY created_at", (kind,)
        ).fetchall()
    return connection.execute("SELECT * FROM items ORDER BY created_at").fetchall()


def set_cursor(connection: sqlite3.Connection, item_id: str, cursor: str) -> None:
    connection.execute("UPDATE items SET sync_cursor = ? WHERE item_id = ?", (cursor, item_id))


def mark_refreshed(connection: sqlite3.Connection, item_id: str) -> None:
    connection.execute(
        "UPDATE items SET last_refreshed_at = ? WHERE item_id = ?",
        (dt.datetime.now().isoformat(timespec="seconds"), item_id),
    )
    connection.commit()


def last_refreshed_at(connection: sqlite3.Connection) -> str | None:
    row = connection.execute("SELECT MAX(last_refreshed_at) AS at FROM items").fetchone()
    return row["at"] if row else None


# --- Accounts --------------------------------------------------------------


def upsert_account(
    connection: sqlite3.Connection,
    *,
    account_id: str,
    item_id: str,
    name: str,
    official_name: str | None,
    mask: str | None,
    type: str,
    subtype: str | None,
    current_balance: float | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO accounts (account_id, item_id, name, official_name, mask, type,
                              subtype, current_balance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (account_id) DO UPDATE SET
            name            = excluded.name,
            official_name   = excluded.official_name,
            mask            = excluded.mask,
            type            = excluded.type,
            subtype         = excluded.subtype,
            -- A spending Refresh sends no balance; keep the one we have.
            current_balance = COALESCE(excluded.current_balance, accounts.current_balance)
        """,
        (account_id, item_id, name, official_name, mask, type, subtype, current_balance),
    )


def list_accounts(connection: sqlite3.Connection) -> list[Account]:
    rows = connection.execute("SELECT * FROM accounts ORDER BY name").fetchall()
    return [
        Account(
            account_id=row["account_id"],
            item_id=row["item_id"],
            name=row["name"],
            official_name=row["official_name"],
            mask=row["mask"],
            type=row["type"],
            subtype=row["subtype"],
            current_balance=row["current_balance"],
        )
        for row in rows
    ]


def account_ids_for_item(connection: sqlite3.Connection, item_id: str) -> list[str]:
    rows = connection.execute(
        "SELECT account_id FROM accounts WHERE item_id = ?", (item_id,)
    ).fetchall()
    return [row["account_id"] for row in rows]


def account_exists(connection: sqlite3.Connection, account_id: str) -> bool:
    found = connection.execute(
        "SELECT 1 FROM accounts WHERE account_id = ?", (account_id,)
    ).fetchone()
    return found is not None
