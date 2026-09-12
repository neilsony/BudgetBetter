"""Refreshing Holdings and trades from Plaid. See ADR-0008.

Holdings are a snapshot — Plaid reports what is held right now, so a Refresh
replaces every Holding for the Item. Investment transactions are a history, so
they are upserted the way spending Transactions are.
"""

import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from typing import Iterable

from budgetbetter.core import db
from budgetbetter.investing import db as investing_db
from budgetbetter.investing.models import Holding, InvestmentTransaction, Security


@dataclass
class HoldingsSnapshot:
    """Everything `/investments/holdings/get` returns."""

    accounts: list[dict] = field(default_factory=list)
    securities: list[dict] = field(default_factory=list)
    holdings: list[dict] = field(default_factory=list)


@dataclass
class InvestmentTransactionPage:
    """One page of `/investments/transactions/get`."""

    securities: list[dict] = field(default_factory=list)
    transactions: list[dict] = field(default_factory=list)
    total: int = 0


@dataclass
class InvestmentsResult:
    holdings: int = 0
    trades: int = 0


def _as_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value[:10])
    return None


def _as_float(value) -> float | None:
    return None if value is None else float(value)


def parse_security(raw: dict) -> Security:
    return Security(
        security_id=raw["security_id"],
        name=raw.get("name"),
        ticker_symbol=raw.get("ticker_symbol"),
        type=str(raw["type"]) if raw.get("type") else None,
        close_price=_as_float(raw.get("close_price")),
        iso_currency_code=raw.get("iso_currency_code"),
        close_price_as_of=_as_date(raw.get("close_price_as_of")),
    )


def parse_holding(raw: dict) -> Holding:
    return Holding(
        account_id=raw["account_id"],
        security_id=raw["security_id"],
        quantity=float(raw.get("quantity") or 0.0),
        institution_price=_as_float(raw.get("institution_price")),
        institution_value=_as_float(raw.get("institution_value")),
        cost_basis=_as_float(raw.get("cost_basis")),
        iso_currency_code=raw.get("iso_currency_code"),
    )


def parse_investment_transaction(raw: dict) -> InvestmentTransaction:
    date = _as_date(raw.get("date"))
    if date is None:
        # Never drop a trade quietly — a missing one silently changes the
        # cost basis the dashboard reports.
        raise ValueError(
            f"Investment transaction {raw.get('investment_transaction_id')!r} "
            f"arrived without a usable date: {raw.get('date')!r}"
        )
    return InvestmentTransaction(
        investment_transaction_id=raw["investment_transaction_id"],
        account_id=raw["account_id"],
        security_id=raw.get("security_id"),
        date=date,
        name=raw.get("name"),
        quantity=_as_float(raw.get("quantity")),
        amount=_as_float(raw.get("amount")),
        price=_as_float(raw.get("price")),
        fees=_as_float(raw.get("fees")),
        type=str(raw["type"]) if raw.get("type") else None,
        subtype=str(raw["subtype"]) if raw.get("subtype") else None,
        iso_currency_code=raw.get("iso_currency_code"),
    )


def _store_accounts(connection: sqlite3.Connection, item_id: str, raw_accounts: Iterable[dict]):
    for raw_account in raw_accounts:
        # Cash is not a Holding: it is whatever the Account balance holds over
        # and above the securities in it. See ADR-0010.
        balances = raw_account.get("balances") or {}
        db.upsert_account(
            connection,
            account_id=raw_account["account_id"],
            item_id=item_id,
            name=raw_account.get("name") or "Account",
            official_name=raw_account.get("official_name"),
            mask=raw_account.get("mask"),
            type=str(raw_account.get("type") or "investment"),
            subtype=str(raw_account.get("subtype")) if raw_account.get("subtype") else None,
            current_balance=_as_float(balances.get("current")),
        )


def _store_securities(connection: sqlite3.Connection, raw_securities: Iterable[dict]) -> None:
    for raw_security in raw_securities:
        investing_db.upsert_security(connection, parse_security(raw_security))


def _account_ids_for(connection: sqlite3.Connection, item_id: str) -> list[str]:
    rows = connection.execute(
        "SELECT account_id FROM accounts WHERE item_id = ?", (item_id,)
    ).fetchall()
    return [row["account_id"] for row in rows]


def apply_holdings_snapshot(
    connection: sqlite3.Connection, item_id: str, snapshot: HoldingsSnapshot
) -> int:
    """Replace this Item's Holdings with the snapshot Plaid just reported."""
    _store_accounts(connection, item_id, snapshot.accounts)
    _store_securities(connection, snapshot.securities)

    holdings = [parse_holding(raw) for raw in snapshot.holdings]
    # Clearing by Account rather than globally keeps other brokers intact, and
    # covers Accounts that now hold nothing at all.
    account_ids = set(_account_ids_for(connection, item_id))
    account_ids.update(holding.account_id for holding in holdings)

    investing_db.replace_holdings(connection, account_ids, holdings)
    connection.commit()
    return len(holdings)


def apply_investment_transactions(
    connection: sqlite3.Connection, item_id: str, page: InvestmentTransactionPage
) -> int:
    """Store one page of trades, leaving already-stored ones correct."""
    _store_securities(connection, page.securities)
    for raw in page.transactions:
        investing_db.upsert_investment_transaction(connection, parse_investment_transaction(raw))
    connection.commit()
    return len(page.transactions)


def refresh_investments(
    connection: sqlite3.Connection,
    item_id: str,
    fetch_holdings,
    fetch_transactions,
    *,
    max_pages: int = 100,
) -> InvestmentsResult:
    """Pull Holdings and trade history for one investing Item.

    The two fetchers are injected so this loop can be exercised without
    touching the network.
    """
    result = InvestmentsResult()
    result.holdings = apply_holdings_snapshot(connection, item_id, fetch_holdings())

    offset = 0
    for _ in range(max_pages):
        page = fetch_transactions(offset)
        stored = apply_investment_transactions(connection, item_id, page)
        offset += stored
        if stored == 0 or offset >= page.total:
            break
    result.trades = offset

    db.mark_refreshed(connection, item_id)
    return result
