"""When an automatic Refresh runs.

A launchd agent wakes daily at noon and asks `is_payday` whether today counts;
the cadence itself lives here so it stays testable. See ADR-0007.
"""

import datetime as dt

# Paydays are every second Friday, counted from this date.
ANCHOR_PAYDAY = dt.date(2026, 8, 21)

PAYDAY_INTERVAL_DAYS = 14


def is_payday(day: dt.date) -> bool:
    """True when `day` falls on the biweekly Friday cycle."""
    return (day - ANCHOR_PAYDAY).days % PAYDAY_INTERVAL_DAYS == 0


def next_payday(after: dt.date) -> dt.date:
    """The first Payday strictly after `after`."""
    days_since_anchor = (after - ANCHOR_PAYDAY).days
    elapsed_cycles = days_since_anchor // PAYDAY_INTERVAL_DAYS
    return ANCHOR_PAYDAY + dt.timedelta(days=(elapsed_cycles + 1) * PAYDAY_INTERVAL_DAYS)
