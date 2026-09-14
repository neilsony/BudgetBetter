# Repayment is Share state with a two-sided claim, not a Settlement

Splitwise-shaped ledgers usually carry two kinds of row: expenses that create debt, and settlements that discharge it. This project has only the first. A Share is marked paid; nothing records the payment as a separate fact.

That is a real simplification and it costs something, so it is worth being explicit about what it buys. Debt here is always attached to the thing that caused it. "You owe Zak $310" is never a bare number — it is always a list of Shares with reasons on them, and clearing one clears exactly one line. A Settlement row that netted against a pool of debts would mean money arriving with no particular Share attached, and then the question "what have I actually paid for?" has no answer.

The payer marks a Share paid. The ower can instead **Claim** it — assert they have sent the money — which surfaces on the payer's dashboard awaiting confirmation and does not clear the debt until the payer confirms.

## Consequences

The Claim step exists because the one-sided version has an obvious failure: you e-transfer someone, they forget to tick the box, and your dashboard says you still owe them with no way to say otherwise. One-sided marking makes the payer the sole authority on whether they were paid, which is precisely the fact most likely to be disputed. Both directions are reversible and both are written to the audit trail, so "who marked this and when" always has an answer.

There are no partial payments. A Share is atomic: paid or not. Someone paying half is a conversation, not a state.

Balances are always derived by walking the Shares, never stored in a column. With Disputes voiding Shares, amendments changing their amounts and departures freezing them, any cached total would need invalidating on every one of those paths, and the first missed invalidation would be silently wrong about money.

## Considered Options

- **A Settlement entity netting against a balance**: rejected as described — it detaches money from the reason it was owed, which is the one thing this ledger exists to keep attached.
- **One-sided marking by the payer only**: rejected — leaves the ower with no recourse when the payer forgets, and that is the common case rather than the edge case.
- **Letting the ower clear their own Share outright**: rejected for the mirror reason. Either side acting alone lets one person decide a two-person fact.
- **Partial payments**: deferred. They would turn every Share into a running balance and every dashboard line into arithmetic, for a situation six people sharing a flat can settle by talking.
