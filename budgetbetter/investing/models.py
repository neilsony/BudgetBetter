"""Investing nouns. Vocabulary follows CONTEXT.md."""

import datetime as dt
from dataclasses import dataclass


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
    close_price_as_of: dt.date | None = None

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
    def effective_price(self) -> float | None:
        """Price per unit, or None if nobody reported one.

        Some brokers (Wealthsimple among them) send 0 rather than null when
        they have no live price, so a zero is treated as missing and the
        Security's last close is used instead. See ADR-0009.
        """
        if self.institution_price:
            return self.institution_price
        if self.security and self.security.close_price:
            return self.security.close_price
        return None

    @property
    def price_is_fallback(self) -> bool:
        """True when the price shown is the Security's last close, not the
        broker's own figure — so the UI can say the value is indicative."""
        return not self.institution_price and self.effective_price is not None

    @property
    def market_value(self) -> float:
        if self.institution_value:
            return self.institution_value
        price = self.effective_price
        return self.quantity * price if price else 0.0

    @property
    def is_priced(self) -> bool:
        return self.institution_value is not None and self.institution_value != 0 or (
            self.effective_price is not None
        )

    @property
    def gain(self) -> float | None:
        """Unrealised gain against cost basis.

        None when there is no cost basis, or when nothing could price the
        Holding — a gain of minus everything would otherwise be reported for
        a position whose value is merely unknown.
        """
        if self.cost_basis is None or not self.is_priced:
            return None
        return self.market_value - self.cost_basis

    @property
    def gain_pct(self) -> float | None:
        if not self.cost_basis or not self.is_priced:
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
