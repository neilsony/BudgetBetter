# Investments live alongside budgeting, not inside it

BudgetBetter now tracks two different things: spending on a bank Item, and Holdings on a brokerage Item. They share the Item, Account and Institution vocabulary but nothing else — a Holding has no Bucket, and a share of an ETF is not spending — so they get separate pages behind a sidebar rather than being forced into one dashboard.

Each Item records the `kind` it was linked for (`budgeting` or `investing`), which decides both the Plaid product requested at Link time (`transactions` vs `investments`) and which Refresh button touches it. Without that, linking a brokerage would have asked Plaid for transaction access it cannot grant, and a spending Refresh would have failed on every investment Item.

## Consequences

Holdings are a **snapshot**, not a history: Plaid reports what is held right now, so a Refresh deletes and re-inserts every Holding for that Item's Accounts rather than upserting. That is scoped per Account so refreshing one broker never clears another's positions, and it means a sold-out position correctly disappears. Investment transactions are a genuine history and are upserted by id like spending Transactions.

Canadian brokerages frequently omit `cost_basis`. Every gain figure is therefore optional, and the dashboard says "Not reported" rather than showing a gain of zero against a cost basis of zero.

## Considered Options

- **One combined dashboard**: rejected — netting a portfolio's value into a spending total produces a number that means nothing.
- **Reusing Buckets for holdings**: rejected — asset allocation is a different question from "what did I spend on groceries", and forcing one taxonomy onto both would corrupt the spending totals that ADR-0004 protects.
