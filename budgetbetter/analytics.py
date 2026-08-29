"""Dashboard figures: what was spent, per Bucket and over time.

Internal Transfers and income never count as spending. See ADR-0004.
"""

import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from budgetbetter import db
from budgetbetter.buckets import INCOME, NON_SPENDING_BUCKETS

Granularity = Literal["week", "month"]


@dataclass
class SpendingSummary:
    """The tiles across the top of the dashboard."""

    total_spending: float = 0.0
    total_income: float = 0.0
    by_bucket: dict[str, float] = field(default_factory=dict)
    transaction_count: int = 0


@dataclass
class TrendPoint:
    period_start: dt.date
    label: str
    spending: float


def category_totals(
    connection: sqlite3.Connection,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    account_id: str | None = None,
) -> SpendingSummary:
    """Spending per Bucket over a period, summed across every Account."""
    transactions = db.list_transactions(
        connection, start=start, end=end, account_id=account_id
    )

    summary = SpendingSummary(transaction_count=len(transactions))
    for transaction in transactions:
        bucket = transaction.effective_bucket
        if bucket == INCOME:
            # Plaid signs money arriving as negative; show it as a positive figure.
            summary.total_income += -transaction.amount
            continue
        if bucket in NON_SPENDING_BUCKETS:
            continue
        summary.by_bucket[bucket] = summary.by_bucket.get(bucket, 0.0) + transaction.amount
        summary.total_spending += transaction.amount

    summary.total_spending = round(summary.total_spending, 2)
    summary.total_income = round(summary.total_income, 2)
    summary.by_bucket = {
        bucket: round(amount, 2)
        for bucket, amount in sorted(
            summary.by_bucket.items(), key=lambda pair: pair[1], reverse=True
        )
    }
    return summary


def period_start_for(day: dt.date, granularity: Granularity) -> dt.date:
    if granularity == "week":
        return day - dt.timedelta(days=day.weekday())
    return day.replace(day=1)


def _step_back(period_start: dt.date, granularity: Granularity, periods: int) -> dt.date:
    if granularity == "week":
        return period_start - dt.timedelta(weeks=periods)
    month_index = period_start.year * 12 + (period_start.month - 1) - periods
    return dt.date(month_index // 12, month_index % 12 + 1, 1)


def _label(period_start: dt.date, granularity: Granularity) -> str:
    if granularity == "week":
        return period_start.strftime("%b %-d")
    return period_start.strftime("%b %Y")


def trend_series(
    connection: sqlite3.Connection,
    granularity: Granularity = "month",
    *,
    periods: int = 12,
    account_id: str | None = None,
    today: dt.date | None = None,
) -> list[TrendPoint]:
    """Spending per period, oldest first, with empty periods kept as zeroes."""
    today = today or dt.date.today()
    current_period = period_start_for(today, granularity)
    first_period = _step_back(current_period, granularity, periods - 1)

    totals: dict[dt.date, float] = {}
    starts: list[dt.date] = []
    cursor = first_period
    while cursor <= current_period:
        totals[cursor] = 0.0
        starts.append(cursor)
        cursor = _step_back(cursor, granularity, -1)

    for transaction in db.list_transactions(
        connection, start=first_period, account_id=account_id
    ):
        if transaction.effective_bucket in NON_SPENDING_BUCKETS:
            continue
        bucket_start = period_start_for(transaction.date, granularity)
        if bucket_start in totals:
            totals[bucket_start] += transaction.amount

    return [
        TrendPoint(
            period_start=start,
            label=_label(start, granularity),
            spending=round(totals[start], 2),
        )
        for start in starts
    ]
