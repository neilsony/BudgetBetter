"""The domain nouns. Vocabulary follows CONTEXT.md."""

import datetime as dt
from dataclasses import dataclass
from typing import Literal

RuleKind = Literal["merchant", "plaid_category"]


@dataclass(frozen=True)
class Rule:
    """A mapping from a Merchant keyword or a Plaid Category to a Bucket."""

    kind: RuleKind
    pattern: str
    bucket: str


@dataclass(frozen=True)
class Account:
    """A single account inside an Item."""

    account_id: str
    item_id: str
    name: str
    official_name: str | None
    mask: str | None
    type: str
    subtype: str | None

    @property
    def display_name(self) -> str:
        suffix = f" ••{self.mask}" if self.mask else ""
        return f"{self.name}{suffix}"


@dataclass(frozen=True)
class Transaction:
    """One posted or pending entry on an Account.

    `amount` follows Plaid's sign convention: positive when money leaves the
    Account, negative when it arrives.
    """

    transaction_id: str
    account_id: str
    date: dt.date
    name: str
    merchant_name: str | None
    amount: float
    pending: bool
    plaid_primary: str | None
    plaid_detailed: str | None
    bucket: str
    override_bucket: str | None = None

    @property
    def effective_bucket(self) -> str:
        return self.override_bucket or self.bucket

    @property
    def display_merchant(self) -> str:
        return self.merchant_name or self.name


@dataclass(frozen=True)
class Security:
    """An instrument that can be held in an investment Account — a stock, an
    ETF, a mutual fund, cash. Identified by Plaid's `security_id`."""

    security_id: str
    name: str | None
    ticker_symbol: str | None
    type: str | None
    close_price: float | None
    iso_currency_code: str | None

    @property
    def display_name(self) -> str:
        return self.ticker_symbol or self.name or "—"


@dataclass(frozen=True)
class Holding:
    """How much of one Security an Account holds right now. A snapshot, not a
    history — every Refresh replaces it. See ADR-0008."""

    account_id: str
    security_id: str
    quantity: float
    institution_price: float | None
    institution_value: float | None
    cost_basis: float | None
    iso_currency_code: str | None
    security: Security | None = None

    @property
    def market_value(self) -> float:
        if self.institution_value is not None:
            return self.institution_value
        return self.quantity * (self.institution_price or 0.0)

    @property
    def gain(self) -> float | None:
        """Unrealised gain against cost basis, or None if Plaid gave no basis."""
        if self.cost_basis is None:
            return None
        return self.market_value - self.cost_basis

    @property
    def gain_pct(self) -> float | None:
        if not self.cost_basis:
            return None
        return (self.market_value - self.cost_basis) / self.cost_basis * 100


@dataclass(frozen=True)
class InvestmentTransaction:
    """One buy, sell, dividend, fee, or transfer on an investment Account.

    `amount` follows Plaid's sign convention: positive when cash leaves the
    Account (a buy), negative when cash arrives (a sell or dividend).
    """

    investment_transaction_id: str
    account_id: str
    security_id: str | None
    date: dt.date
    name: str | None
    quantity: float | None
    amount: float | None
    price: float | None
    fees: float | None
    type: str | None
    subtype: str | None
    iso_currency_code: str | None
    security: Security | None = None

    @property
    def display_name(self) -> str:
        return self.name or (self.subtype or self.type or "—")
