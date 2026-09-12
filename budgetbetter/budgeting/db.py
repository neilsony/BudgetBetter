"""Spending tables: Transactions and Rules. See ADR-0012.

Connection handling, Items and Accounts live in `budgetbetter.core.db`.
"""

import datetime as dt
import sqlite3
from typing import Iterable

from budgetbetter.budgeting.models import Rule, Transaction


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


