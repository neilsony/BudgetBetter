# Two-layer categorisation with Override precedence

Every Transaction keeps the Plaid Category verbatim, and its Bucket is derived from that by a Rule table the owner can edit, with a per-Transaction Override beating every Rule. We keep both layers because Plaid's taxonomy is good at recognising merchants but is not the owner's vocabulary — it has no notion of "drinking" as distinct from "eating out" — while a pure hand-tagging approach would mean touching hundreds of Transactions a month.

Precedence is fixed: **Override, then Merchant-keyword Rule, then Plaid Category Rule, then `other`.** Re-running a Refresh re-derives Buckets for added and modified Transactions but never disturbs an Override.

## Considered Options

- **Display Plaid Categories directly**: no Buckets to maintain, but the owner cannot express their own categories.
- **Merchant keyword rules only**: no dependency on Plaid's taxonomy, but every new merchant is uncategorised until a rule is written by hand.
