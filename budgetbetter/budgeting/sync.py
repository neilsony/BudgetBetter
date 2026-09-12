"""Refreshing Transactions from Plaid. See ADR-0002.

A Refresh pages through `/transactions/sync` until Plaid says there is no more,
committing each page before advancing the cursor so an interrupted Refresh
re-fetches the page it was on rather than skipping it.
"""

import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from typing import Iterable

from budgetbetter import db
from budgetbetter.buckets import NON_SPENDING_BUCKETS, TRANSFERS
from budgetbetter.categorize import Rule, is_internal_transfer, resolve_bucket
from budgetbetter.models import Transaction


@dataclass
class SyncPage:
    """One page of changes as Plaid describes them."""

    added: list[dict] = field(default_factory=list)
    modified: list[dict] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    next_cursor: str = ""
    has_more: bool = False
    accounts: list[dict] = field(default_factory=list)


@dataclass
class RefreshResult:
    added: int = 0
    modified: int = 0
    removed: int = 0

    @property
    def total_changes(self) -> int:
        return self.added + self.modified + self.removed


def parse_transaction(raw: dict, rules: Iterable[Rule]) -> Transaction:
    """Turn Plaid's Transaction shape into ours, deriving its Bucket."""
    category = raw.get("personal_finance_category") or {}
    if not isinstance(category, dict):  # plaid-python returns a model object
        category = {"primary": getattr(category, "primary", None),
                    "detailed": getattr(category, "detailed", None)}

    date = raw.get("date")
    if isinstance(date, str):
        date = dt.date.fromisoformat(date)
    elif isinstance(date, dt.datetime):
        date = date.date()
    if not isinstance(date, dt.date):
        # Never drop a Transaction quietly: money going missing from the
        # dashboard is worse than a Refresh that stops and says why.
        raise ValueError(
            f"Transaction {raw.get('transaction_id')!r} arrived without a usable date: {date!r}"
        )

    transaction = Transaction(
        transaction_id=raw["transaction_id"],
        account_id=raw["account_id"],
        date=date,
        name=raw.get("name") or "",
        merchant_name=raw.get("merchant_name"),
        amount=float(raw.get("amount") or 0.0),
        pending=bool(raw.get("pending")),
        plaid_primary=category.get("primary"),
        plaid_detailed=category.get("detailed"),
        bucket="other",
    )
    # The Bucket is derived from the Rules; an Override, if any, lives in the
    # database and is applied when the Transaction is read back.
    bucket = resolve_bucket(transaction, rules)

    # ADR-0004 must hold even if someone edits the Rules table: money that only
    # moved between the owner's own Accounts is never spending.
    if bucket not in NON_SPENDING_BUCKETS and is_internal_transfer(transaction):
        bucket = TRANSFERS

    return replace_bucket(transaction, bucket)


def replace_bucket(transaction: Transaction, bucket: str) -> Transaction:
    return Transaction(
        transaction_id=transaction.transaction_id,
        account_id=transaction.account_id,
        date=transaction.date,
        name=transaction.name,
        merchant_name=transaction.merchant_name,
        amount=transaction.amount,
        pending=transaction.pending,
        plaid_primary=transaction.plaid_primary,
        plaid_detailed=transaction.plaid_detailed,
        bucket=bucket,
        override_bucket=transaction.override_bucket,
    )


def apply_sync_page(
    connection: sqlite3.Connection,
    item_id: str,
    page: SyncPage,
    rules: Iterable[Rule],
) -> RefreshResult:
    """Apply one page of changes and advance the Item's cursor, atomically."""
    rules = list(rules)

    for raw_account in page.accounts:
        db.upsert_account(
            connection,
            account_id=raw_account["account_id"],
            item_id=item_id,
            name=raw_account.get("name") or "Account",
            official_name=raw_account.get("official_name"),
            mask=raw_account.get("mask"),
            type=str(raw_account.get("type") or "other"),
            subtype=str(raw_account.get("subtype")) if raw_account.get("subtype") else None,
        )

    for raw in list(page.added) + list(page.modified):
        transaction = parse_transaction(raw, rules)
        _ensure_account(connection, item_id, transaction.account_id)
        db.upsert_transaction(connection, transaction)

    db.delete_transactions(connection, page.removed)

    if page.next_cursor:
        db.set_cursor(connection, item_id, page.next_cursor)

    connection.commit()
    return RefreshResult(
        added=len(page.added), modified=len(page.modified), removed=len(page.removed)
    )


def _ensure_account(connection: sqlite3.Connection, item_id: str, account_id: str) -> None:
    """Plaid occasionally sends a Transaction before its Account.

    Store a placeholder rather than failing the whole Refresh; the next page of
    accounts overwrites it with the real name.
    """
    if not db.account_exists(connection, account_id):
        db.upsert_account(
            connection,
            account_id=account_id,
            item_id=item_id,
            name="Unknown account",
            official_name=None,
            mask=None,
            type="other",
            subtype=None,
        )


def refresh_item(
    connection: sqlite3.Connection,
    item_id: str,
    fetch_page,
    rules: Iterable[Rule],
    *,
    max_pages: int = 200,
) -> RefreshResult:
    """Page through Plaid until it runs out of changes.

    `fetch_page(cursor) -> SyncPage` is the Plaid call, injected so this loop
    can be exercised without touching the network.
    """
    rules = list(rules)
    item = db.get_item(connection, item_id)
    cursor = item["sync_cursor"] if item else None

    totals = RefreshResult()
    complete = False
    for _ in range(max_pages):
        page = fetch_page(cursor)
        result = apply_sync_page(connection, item_id, page, rules)
        totals.added += result.added
        totals.modified += result.modified
        totals.removed += result.removed
        # An empty cursor is not a position: sending it back would read as a
        # first call and re-pull the whole backfill, so keep the one we have.
        if page.next_cursor:
            cursor = page.next_cursor
        if not page.has_more:
            complete = True
            break

    if not complete:
        raise RuntimeError(
            f"Item {item_id} still had more Transactions after {max_pages} pages. "
            "The pages already fetched are saved; run another Refresh to continue."
        )

    db.mark_refreshed(connection, item_id)
    return totals
