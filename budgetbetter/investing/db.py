"""Investing tables: Securities, Holdings and trade history. See ADR-0012.

Connection handling, Items and Accounts live in `budgetbetter.core.db`.
"""

import datetime as dt
import sqlite3
from typing import Iterable

from budgetbetter.investing.models import Holding, InvestmentTransaction, Security


# --- Securities ------------------------------------------------------------


def _to_security(row: sqlite3.Row) -> Security:
    return Security(
        security_id=row["security_id"],
        name=row["name"],
        ticker_symbol=row["ticker_symbol"],
        type=row["type"],
        close_price=row["close_price"],
        iso_currency_code=row["iso_currency_code"],
        close_price_as_of=(
            dt.date.fromisoformat(row["close_price_as_of"])
            if row["close_price_as_of"]
            else None
        ),
    )


def upsert_security(connection: sqlite3.Connection, security: Security) -> None:
    connection.execute(
        """
        INSERT INTO securities (security_id, name, ticker_symbol, type,
                                close_price, close_price_as_of, iso_currency_code)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (security_id) DO UPDATE SET
            name              = excluded.name,
            ticker_symbol     = excluded.ticker_symbol,
            type              = excluded.type,
            close_price       = excluded.close_price,
            close_price_as_of = excluded.close_price_as_of,
            iso_currency_code = excluded.iso_currency_code
        """,
        (
            security.security_id,
            security.name,
            security.ticker_symbol,
            security.type,
            security.close_price,
            security.close_price_as_of.isoformat() if security.close_price_as_of else None,
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
