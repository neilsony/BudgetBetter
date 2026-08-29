# Internal Transfers are excluded from spending totals

A credit card payment appears twice in the data — as a debit on the chequing Account and a credit on the card Account — while the actual spending was already recorded when the card was used. Counting either leg would inflate spending, so Transactions classified as the `transfers` Bucket are excluded from every spending total and trend on the dashboard.

Spending totals are grouped across all Accounts of all Items rather than per Account, because the owner thinks in terms of what they spent, not which card carried it; Account is available as a filter and shown per Transaction, but is never the unit of the totals.

## Consequences

`income` is likewise kept out of the spending total and reported on its own tile, so "total spending" stays a spending number rather than a net cash-flow one. A missed Internal Transfer therefore shows up as inflated spending, which makes transfer detection worth testing carefully.
