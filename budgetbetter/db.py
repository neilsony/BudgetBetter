"""The local SQLite store. See ADR-0001."""

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Iterable

from budgetbetter.categorize import Rule
from budgetbetter.models import (
    Account,
    Holding,
    InvestmentTransaction,
    Security,
    Transaction,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(database: str | Path) -> sqlite3.Connection:
    # One connection per request, never shared concurrently — but FastAPI may run
    # the dependency that opens it and the endpoint that uses it on different
    # threadpool workers, which SQLite otherwise refuses.
    connection = sqlite3.connect(database, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialise(connection: sqlite3.Connection) -> None:
    """Create the schema, and seed the Rules table if it is empty."""
    connection.executescript(SCHEMA_PATH.read_text())
    _migrate(connection)
    connection.commit()

    already_seeded = connection.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
    if not already_seeded:
        from budgetbetter.buckets import SEED_RULES

        replace_rules(connection, SEED_RULES)


def _migrate(connection: sqlite3.Connection) -> None:
    """Add columns that CREATE TABLE IF NOT EXISTS cannot add to an existing table."""
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(items)")}
    if "kind" not in columns:
        connection.execute(
            "ALTER TABLE items ADD COLUMN kind TEXT NOT NULL DEFAULT 'budgeting'"
        )


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
    row = connection.execute(
        "SELECT MAX(last_refreshed_at) AS at FROM items"
    ).fetchone()
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
) -> None:
    connection.execute(
        """
        INSERT INTO accounts (account_id, item_id, name, official_name, mask, type, subtype)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (account_id) DO UPDATE SET
            name          = excluded.name,
            official_name = excluded.official_name,
            mask          = excluded.mask,
            type          = excluded.type,
            subtype       = excluded.subtype
        """,
        (account_id, item_id, name, official_name, mask, type, subtype),
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
        )
        for row in rows
    ]


def account_exists(connection: sqlite3.Connection, account_id: str) -> bool:
    found = connection.execute(
        "SELECT 1 FROM accounts WHERE account_id = ?", (account_id,)
    ).fetchone()
    return found is not None


# --- Transactions ----------------------------------------------------------


def _to_transaction(row: sqlite3.Row) -> Transaction:
    return Transaction(
        transaction_id=row["transaction_id"],
        account_id=row["account_id"],
        date=dt.date.fromisoformat(row["date"]),
        name=row["name"],
        merchant_name=row["merchant_name"],
        amount=row["amount"],
        pending=bool(row["pending"]),
        plaid_primary=row["plaid_primary"],
        plaid_detailed=row["plaid_detailed"],
        bucket=row["bucket"],
        override_bucket=row["override_bucket"],
    )


def upsert_transaction(connection: sqlite3.Connection, transaction: Transaction) -> None:
    """Store a Transaction, leaving any existing Override untouched."""
    connection.execute(
        """
        INSERT INTO transactions (transaction_id, account_id, date, name, merchant_name,
                                  amount, pending, plaid_primary, plaid_detailed, bucket)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (transaction_id) DO UPDATE SET
            account_id     = excluded.account_id,
            date           = excluded.date,
            name           = excluded.name,
            merchant_name  = excluded.merchant_name,
            amount         = excluded.amount,
            pending        = excluded.pending,
            plaid_primary  = excluded.plaid_primary,
            plaid_detailed = excluded.plaid_detailed,
            bucket         = excluded.bucket
        """,
        (
            transaction.transaction_id,
            transaction.account_id,
            transaction.date.isoformat(),
            transaction.name,
            transaction.merchant_name,
            transaction.amount,
            int(transaction.pending),
            transaction.plaid_primary,
            transaction.plaid_detailed,
            transaction.bucket,
        ),
    )


def delete_transactions(connection: sqlite3.Connection, transaction_ids: Iterable[str]) -> None:
    connection.executemany(
        "DELETE FROM transactions WHERE transaction_id = ?",
        [(transaction_id,) for transaction_id in transaction_ids],
    )


def list_transactions(
    connection: sqlite3.Connection,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    account_id: str | None = None,
    limit: int | None = None,
) -> list[Transaction]:
    query = "SELECT * FROM transactions WHERE 1 = 1"
    parameters: list[object] = []
    if start:
        query += " AND date >= ?"
        parameters.append(start.isoformat())
    if end:
        query += " AND date <= ?"
        parameters.append(end.isoformat())
    if account_id:
        query += " AND account_id = ?"
        parameters.append(account_id)
    query += " ORDER BY date DESC, transaction_id"
    if limit is not None:
        query += " LIMIT ?"
        parameters.append(limit)
    return [_to_transaction(row) for row in connection.execute(query, parameters).fetchall()]


def set_override(connection: sqlite3.Connection, transaction_id: str, bucket: str | None) -> None:
    connection.execute(
        "UPDATE transactions SET override_bucket = ? WHERE transaction_id = ?",
        (bucket, transaction_id),
    )
    connection.commit()


# --- Rules -----------------------------------------------------------------


def list_rules(connection: sqlite3.Connection) -> list[Rule]:
    rows = connection.execute("SELECT kind, pattern, bucket FROM rules ORDER BY id").fetchall()
    return [Rule(row["kind"], row["pattern"], row["bucket"]) for row in rows]


def replace_rules(connection: sqlite3.Connection, rules: Iterable[Rule]) -> None:
    connection.execute("DELETE FROM rules")
    connection.executemany(
        "INSERT INTO rules (kind, pattern, bucket) VALUES (?, ?, ?)",
        [(rule.kind, rule.pattern, rule.bucket) for rule in rules],
    )
    connection.commit()


# --- Securities ------------------------------------------------------------


def _to_security(row: sqlite3.Row) -> Security:
    return Security(
        security_id=row["security_id"],
        name=row["name"],
        ticker_symbol=row["ticker_symbol"],
        type=row["type"],
        close_price=row["close_price"],
        iso_currency_code=row["iso_currency_code"],
    )


def upsert_security(connection: sqlite3.Connection, security: Security) -> None:
    connection.execute(
        """
        INSERT INTO securities (security_id, name, ticker_symbol, type,
                                close_price, iso_currency_code)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (security_id) DO UPDATE SET
            name              = excluded.name,
            ticker_symbol     = excluded.ticker_symbol,
            type              = excluded.type,
            close_price       = excluded.close_price,
            iso_currency_code = excluded.iso_currency_code
        """,
        (
            security.security_id,
            security.name,
            security.ticker_symbol,
            security.type,
            security.close_price,
            security.iso_currency_code,
        ),
    )


def securities_by_id(connection: sqlite3.Connection) -> dict[str, Security]:
    rows = connection.execute("SELECT * FROM securities").fetchall()
    return {row["security_id"]: _to_security(row) for row in rows}


# --- Holdings --------------------------------------------------------------


def replace_holdings(
    connection: sqlite3.Connection, account_ids: Iterable[str], holdings: Iterable[Holding]
) -> None:
    """Swap in a fresh snapshot for the given Accounts. See ADR-0008.

    Scoped to the Accounts of one Item so refreshing one broker never clears
    another's positions.
    """
    connection.executemany(
        "DELETE FROM holdings WHERE account_id = ?",
        [(account_id,) for account_id in account_ids],
    )
    connection.executemany(
        """
        INSERT INTO holdings (account_id, security_id, quantity, institution_price,
                              institution_value, cost_basis, iso_currency_code)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (account_id, security_id) DO UPDATE SET
            quantity          = excluded.quantity,
            institution_price = excluded.institution_price,
            institution_value = excluded.institution_value,
            cost_basis        = excluded.cost_basis,
            iso_currency_code = excluded.iso_currency_code
        """,
        [
            (
                holding.account_id,
                holding.security_id,
                holding.quantity,
                holding.institution_price,
                holding.institution_value,
                holding.cost_basis,
                holding.iso_currency_code,
            )
            for holding in holdings
        ],
    )


def list_holdings(
    connection: sqlite3.Connection, *, account_id: str | None = None
) -> list[Holding]:
    query = "SELECT * FROM holdings"
    parameters: list[object] = []
    if account_id:
        query += " WHERE account_id = ?"
        parameters.append(account_id)
    rows = connection.execute(query, parameters).fetchall()

    securities = securities_by_id(connection)
    holdings = [
        Holding(
            account_id=row["account_id"],
            security_id=row["security_id"],
            quantity=row["quantity"],
            institution_price=row["institution_price"],
            institution_value=row["institution_value"],
            cost_basis=row["cost_basis"],
            iso_currency_code=row["iso_currency_code"],
            security=securities.get(row["security_id"]),
        )
        for row in rows
    ]
    return sorted(holdings, key=lambda holding: holding.market_value, reverse=True)


# --- Investment transactions -----------------------------------------------


def upsert_investment_transaction(
    connection: sqlite3.Connection, transaction: InvestmentTransaction
) -> None:
    connection.execute(
        """
        INSERT INTO investment_transactions (
            investment_transaction_id, account_id, security_id, date, name,
            quantity, amount, price, fees, type, subtype, iso_currency_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (investment_transaction_id) DO UPDATE SET
            account_id        = excluded.account_id,
            security_id       = excluded.security_id,
            date              = excluded.date,
            name              = excluded.name,
            quantity          = excluded.quantity,
            amount            = excluded.amount,
            price             = excluded.price,
            fees              = excluded.fees,
            type              = excluded.type,
            subtype           = excluded.subtype,
            iso_currency_code = excluded.iso_currency_code
        """,
        (
            transaction.investment_transaction_id,
            transaction.account_id,
            transaction.security_id,
            transaction.date.isoformat(),
            transaction.name,
            transaction.quantity,
            transaction.amount,
            transaction.price,
            transaction.fees,
            transaction.type,
            transaction.subtype,
            transaction.iso_currency_code,
        ),
    )


def list_investment_transactions(
    connection: sqlite3.Connection,
    *,
    account_id: str | None = None,
    limit: int | None = None,
) -> list[InvestmentTransaction]:
    query = "SELECT * FROM investment_transactions WHERE 1 = 1"
    parameters: list[object] = []
    if account_id:
        query += " AND account_id = ?"
        parameters.append(account_id)
    query += " ORDER BY date DESC, investment_transaction_id"
    if limit is not None:
        query += " LIMIT ?"
        parameters.append(limit)

    securities = securities_by_id(connection)
    return [
        InvestmentTransaction(
            investment_transaction_id=row["investment_transaction_id"],
            account_id=row["account_id"],
            security_id=row["security_id"],
            date=dt.date.fromisoformat(row["date"]),
            name=row["name"],
            quantity=row["quantity"],
            amount=row["amount"],
            price=row["price"],
            fees=row["fees"],
            type=row["type"],
            subtype=row["subtype"],
            iso_currency_code=row["iso_currency_code"],
            security=securities.get(row["security_id"]) if row["security_id"] else None,
        )
        for row in connection.execute(query, parameters).fetchall()
    ]
