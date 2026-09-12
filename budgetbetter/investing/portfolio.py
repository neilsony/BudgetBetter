"""Portfolio figures: what is held, what it cost, what it is worth now.

Three numbers matter and they are not the same. **Securities** is what the
Holdings are worth. **Cash** is whatever the Account balance holds over and
above them. **Value** is the two together, and is the figure the broker's own
app shows. Gain is measured against securities only — cash was never a gain.

See ADR-0008, ADR-0009 and ADR-0010.
"""

import sqlite3
from dataclasses import dataclass, field

from budgetbetter.core import db
from budgetbetter.investing import db as investing_db
from budgetbetter.investing.models import Holding

# Investment transaction subtypes that move money in or out of the Account from
# outside it. A dividend is deliberately absent: money the Account earned is a
# return, not a contribution, and counting it as one would understate the gain.
# See ADR-0011.
EXTERNAL_FLOW_SUBTYPES = {
    "deposit",
    "withdrawal",
    "contribution",
    "transfer",
    "send",
}


@dataclass
class AccountPosition:
    """One investment Account's slice of the portfolio."""

    account_id: str
    name: str
    securities: float = 0.0
    cost_basis: float = 0.0
    balance: float | None = None
    holdings: list[Holding] = field(default_factory=list)

    @property
    def cash(self) -> float:
        """Uninvested cash in the Account.

        Clamped at zero: last-close prices can briefly exceed what the broker
        reports, and a negative cash figure would be a pricing artefact rather
        than anything real.
        """
        if self.balance is None:
            return 0.0
        return round(max(self.balance - self.securities, 0.0), 2)

    @property
    def value(self) -> float:
        """Total worth. The broker's balance when it gave one, since that is
        the number its own app shows and it already includes cash."""
        if self.balance is None:
            return round(self.securities, 2)
        return round(self.balance, 2)

    @property
    def gain(self) -> float | None:
        return None if not self.cost_basis else round(self.securities - self.cost_basis, 2)

    @property
    def gain_pct(self) -> float | None:
        if not self.cost_basis:
            return None
        return round((self.securities - self.cost_basis) / self.cost_basis * 100, 2)


@dataclass
class PortfolioSummary:
    total_value: float = 0.0
    total_securities: float = 0.0
    total_cash: float = 0.0
    total_cost_basis: float = 0.0
    # Money paid in from outside, net of anything taken out. See ADR-0011.
    net_contributions: float = 0.0
    holding_count: int = 0
    # Holdings nothing could price. Their cost basis is excluded from the
    # totals, so an unpriced position is not reported as a total loss.
    unpriced_count: int = 0
    accounts: list[AccountPosition] = field(default_factory=list)

    @property
    def all_time_gain(self) -> float:
        """Everything the Account has made since it opened.

        Unlike `total_gain` this counts realised gains, dividends and cash, so
        it is the figure the broker's own app reports.
        """
        return round(self.total_value - self.net_contributions, 2)

    @property
    def all_time_gain_pct(self) -> float:
        if not self.net_contributions:
            return 0.0
        return round(
            (self.total_value - self.net_contributions) / self.net_contributions * 100, 2
        )

    @property
    def has_contributions(self) -> bool:
        """False when no external cash flow was recorded, so an all-time
        return cannot be computed."""
        return self.net_contributions > 0

    @property
    def total_gain(self) -> float:
        return round(self.total_securities - self.total_cost_basis, 2)

    @property
    def total_gain_pct(self) -> float:
        if not self.total_cost_basis:
            return 0.0
        return round(
            (self.total_securities - self.total_cost_basis) / self.total_cost_basis * 100, 2
        )

    @property
    def has_cost_basis(self) -> bool:
        """False when the broker reported no cost basis, so gain is unknowable."""
        return self.total_cost_basis > 0


def portfolio_summary(
    connection: sqlite3.Connection, *, account_id: str | None = None
) -> PortfolioSummary:
    """Current value, cash and unrealised gain, per Account and overall."""
    holdings = investing_db.list_holdings(connection, account_id=account_id)
    accounts = {
        account.account_id: account
        for account in db.list_accounts(connection)
        if account_id is None or account.account_id == account_id
    }

    summary = PortfolioSummary(holding_count=len(holdings))
    positions: dict[str, AccountPosition] = {}

    def position_for(aid: str) -> AccountPosition:
        account = accounts.get(aid)
        return positions.setdefault(
            aid,
            AccountPosition(
                account_id=aid,
                name=account.display_name if account else "Account",
                balance=account.current_balance if account else None,
            ),
        )

    for holding in holdings:
        position = position_for(holding.account_id)
        position.holdings.append(holding)

        if not holding.is_priced:
            # Counting its cost basis without a value would report the whole
            # position as a 100% loss. Leave it out of both sides instead.
            summary.unpriced_count += 1
            continue

        position.securities += holding.market_value
        position.cost_basis += holding.cost_basis or 0.0

    # An Account can hold nothing but cash and still belongs on the page.
    for aid, account in accounts.items():
        if account.current_balance:
            position_for(aid)

    for position in positions.values():
        position.securities = round(position.securities, 2)
        position.cost_basis = round(position.cost_basis, 2)

        summary.total_securities += position.securities
        summary.total_cost_basis += position.cost_basis
        summary.total_cash += position.cash
        summary.total_value += position.value

    summary.total_securities = round(summary.total_securities, 2)
    summary.total_cost_basis = round(summary.total_cost_basis, 2)
    summary.total_cash = round(summary.total_cash, 2)
    summary.total_value = round(summary.total_value, 2)

    summary.net_contributions = net_contributions(connection, account_id=account_id)

    summary.accounts = sorted(positions.values(), key=lambda p: p.value, reverse=True)
    return summary


def net_contributions(
    connection: sqlite3.Connection, *, account_id: str | None = None
) -> float:
    """Money paid into the Account from outside, net of what was taken out.

    Plaid signs cash arriving as negative, so the sum is negated to read as a
    contribution. Buys and sells move money *within* the Account and are not
    counted; neither are dividends, which the Account earned rather than
    received from the owner. See ADR-0011.
    """
    total = 0.0
    for transaction in investing_db.list_investment_transactions(connection, account_id=account_id):
        subtype = (transaction.subtype or "").lower()
        type_ = (transaction.type or "").lower()
        if subtype in EXTERNAL_FLOW_SUBTYPES or type_ == "transfer":
            total += transaction.amount or 0.0
    return round(-total, 2)


@dataclass
class AllocationSlice:
    label: str
    value: float
    share: float


def allocation(connection: sqlite3.Connection, *, account_id: str | None = None):
    """Share of the portfolio held in each Security, largest first.

    Cash is a slice like any other — leaving it out would make a portfolio
    that is half cash look fully invested.
    """
    summary = portfolio_summary(connection, account_id=account_id)
    if not summary.total_value:
        return []

    by_security: dict[str, float] = {}
    for position in summary.accounts:
        for holding in position.holdings:
            if not holding.is_priced:
                continue
            label = holding.security.display_name if holding.security else holding.security_id
            by_security[label] = by_security.get(label, 0.0) + holding.market_value

    if summary.total_cash:
        by_security["Cash"] = summary.total_cash

    return [
        AllocationSlice(
            label=label,
            value=round(value, 2),
            share=round(value / summary.total_value * 100, 1),
        )
        for label, value in sorted(by_security.items(), key=lambda pair: pair[1], reverse=True)
    ]
