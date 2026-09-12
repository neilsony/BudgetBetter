"""Spending nouns. Vocabulary follows CONTEXT.md."""

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
