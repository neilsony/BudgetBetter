"""Portfolio figures: what is held, what it cost, what it is worth now.

See ADR-0008. Canadian brokers often omit cost basis, so every gain figure is
optional and the tiles say so rather than showing a wrong zero.
"""

import sqlite3
from dataclasses import dataclass, field

from budgetbetter import db
from budgetbetter.models import Holding


@dataclass
class AccountPosition:
    """One investment Account's slice of the portfolio."""

    account_id: str
    name: str
    value: float = 0.0
    cost_basis: float = 0.0
    holdings: list[Holding] = field(default_factory=list)

    @property
    def gain(self) -> float | None:
        return None if not self.cost_basis else self.value - self.cost_basis

    @property
    def gain_pct(self) -> float | None:
        return None if not self.cost_basis else (self.value - self.cost_basis) / self.cost_basis * 100


@dataclass
class PortfolioSummary:
    total_value: float = 0.0
    total_cost_basis: float = 0.0
    holding_count: int = 0
    accounts: list[AccountPosition] = field(default_factory=list)

    @property
    def total_gain(self) -> float:
        return round(self.total_value - self.total_cost_basis, 2)

    @property
    def total_gain_pct(self) -> float:
        if not self.total_cost_basis:
            return 0.0
        return round((self.total_value - self.total_cost_basis) / self.total_cost_basis * 100, 2)

    @property
    def has_cost_basis(self) -> bool:
        """False when the broker reported no cost basis, so gain is unknowable."""
        return self.total_cost_basis > 0


def portfolio_summary(
    connection: sqlite3.Connection, *, account_id: str | None = None
) -> PortfolioSummary:
    """Current value and unrealised gain, per Account and overall."""
    holdings = db.list_holdings(connection, account_id=account_id)
    account_names = {
        account.account_id: account.display_name for account in db.list_accounts(connection)
    }

    summary = PortfolioSummary(holding_count=len(holdings))
    positions: dict[str, AccountPosition] = {}

    for holding in holdings:
        position = positions.setdefault(
            holding.account_id,
            AccountPosition(
                account_id=holding.account_id,
                name=account_names.get(holding.account_id, "Account"),
            ),
        )
        position.value += holding.market_value
        position.cost_basis += holding.cost_basis or 0.0
        position.holdings.append(holding)

        summary.total_value += holding.market_value
        summary.total_cost_basis += holding.cost_basis or 0.0

    summary.total_value = round(summary.total_value, 2)
    summary.total_cost_basis = round(summary.total_cost_basis, 2)
    for position in positions.values():
        position.value = round(position.value, 2)
        position.cost_basis = round(position.cost_basis, 2)

    summary.accounts = sorted(positions.values(), key=lambda p: p.value, reverse=True)
    return summary


@dataclass
class AllocationSlice:
    label: str
    value: float
    share: float


def allocation(connection: sqlite3.Connection, *, account_id: str | None = None):
    """Share of the portfolio held in each Security, largest first."""
    holdings = db.list_holdings(connection, account_id=account_id)
    total = sum(holding.market_value for holding in holdings)
    if not total:
        return []

    by_security: dict[str, float] = {}
    for holding in holdings:
        label = holding.security.display_name if holding.security else holding.security_id
        by_security[label] = by_security.get(label, 0.0) + holding.market_value

    return [
        AllocationSlice(label=label, value=round(value, 2), share=round(value / total * 100, 1))
        for label, value in sorted(by_security.items(), key=lambda pair: pair[1], reverse=True)
    ]
