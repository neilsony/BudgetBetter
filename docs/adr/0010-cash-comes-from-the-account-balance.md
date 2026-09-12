# Cash comes from the Account balance, not from a Holding

Some brokers report uninvested cash as a cash-equivalent Security; Wealthsimple does not. It returns no cash Holding at all, and instead reports each Account's `balances.current` as the whole Account's worth, securities and cash together. Cash is therefore **derived**: the balance minus the value of the Holdings in that Account.

That makes the broker's balance the authority on **Total value**, which is the right outcome — it is the number the owner sees in their own broker's app, and unlike our sum of Holdings it already accounts for positions Plaid could not price.

## Consequences

Three figures now mean three different things, and the page shows all three: **Invested** is what the Holdings are worth, **Cash** is the remainder of the balance, **Total value** is the balance itself. Gain is measured against Invested alone — cash was never a gain, and netting it in would invent one.

Derived cash absorbs any gap between our prices and the broker's, so on an Account holding a Security that Plaid could not price (ADR-0009), some of the "cash" is really that position. The figure is clamped at zero, since last-close prices can briefly exceed the balance and negative cash would be a pricing artefact rather than anything real.

An Account with a balance and no Holdings still appears, so a purely cash account is not invisible.

## Considered Options

- **Summing Holdings for the total**: what the code did first. Excludes cash entirely, and silently drops any position Plaid cannot price.
- **Treating cash as a synthetic Holding**: would let one code path handle both, but invents a Security that the broker never reported and that has no cost basis.
