"""Deriving a Bucket for a Transaction. See ADR-0003.

Precedence is fixed: Override, then Merchant-keyword Rule, then Plaid Category
Rule (detailed before primary), then `other`.
"""

from typing import Iterable

from budgetbetter.buckets import (
    INTERNAL_TRANSFER_DETAILED,
    INTERNAL_TRANSFER_PRIMARY,
    OTHER,
)
from budgetbetter.models import Rule, RuleKind, Transaction

__all__ = ["Rule", "RuleKind", "resolve_bucket", "is_internal_transfer"]


def resolve_bucket(
    transaction: Transaction,
    rules: Iterable[Rule],
    *,
    default: str = OTHER,
) -> str:
    """The Bucket a Transaction belongs to."""
    if transaction.override_bucket:
        return transaction.override_bucket

    rules = list(rules)

    merchant = (transaction.merchant_name or transaction.name or "").lower()
    if merchant:
        for rule in rules:
            if rule.kind == "merchant" and rule.pattern.lower() in merchant:
                return rule.bucket

    # A rule naming the detailed Plaid Category is more specific than one
    # naming the primary, so it wins regardless of rule order.
    for plaid_category in (transaction.plaid_detailed, transaction.plaid_primary):
        if not plaid_category:
            continue
        for rule in rules:
            if rule.kind == "plaid_category" and rule.pattern == plaid_category:
                return rule.bucket

    return default


def is_internal_transfer(transaction: Transaction) -> bool:
    """True when this Transaction only moved money between the owner's Accounts.

    Credit card payments count: the spending was recorded when the card was
    used, so the payment itself is not new spending. See ADR-0004.
    """
    if transaction.plaid_detailed in INTERNAL_TRANSFER_DETAILED:
        return True
    return transaction.plaid_primary in INTERNAL_TRANSFER_PRIMARY
