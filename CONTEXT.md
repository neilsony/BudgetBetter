# BudgetBetter

A single-user personal budgeting tool. It links the owner's bank through Plaid, pulls their Transactions into a local store, sorts each one into a Bucket, and shows spending on a local dashboard.

## Language

### Banking

**Institution**:
The bank itself, as Plaid identifies it (e.g. Royal Bank of Canada).
_Avoid_: bank, provider

**Item**:
One authenticated login at one Institution. Owns the credentials used to fetch data and may hold many Accounts. Linked either for **budgeting** (spending) or for **investing** (holdings), never both.
_Avoid_: connection, login, link

**Account**:
A single account inside an Item — a chequing account, a savings account, or one credit card.
_Avoid_: card, portfolio

**Transaction**:
One posted or pending entry on an Account. Carries a merchant name, an amount, and a date.
_Avoid_: charge, entry, purchase

**Merchant**:
The counterparty on a Transaction, as named by Plaid.
_Avoid_: store, vendor, payee

### Categorisation

**Plaid Category**:
The category Plaid assigns to a Transaction. External, immutable, and never edited by this project.
_Avoid_: category (unqualified)

**Bucket**:
One of this project's own spending categories, such as `groceries` or `rent`. Every Transaction belongs to exactly one.
_Avoid_: category (unqualified), tag, label

**Rule**:
A mapping that derives a Bucket from a Transaction, keyed on either a Plaid Category or a Merchant keyword.
_Avoid_: mapping, classifier

**Override**:
A Bucket set by hand on one Transaction. Beats every Rule and survives later refreshes.
_Avoid_: manual category, correction

**Internal Transfer**:
Money moving between two of the owner's own Accounts, including a credit card payment. Not spending, and excluded from spending totals.
_Avoid_: payment, transfer (unqualified)

### Investing

**Security**:
An instrument that can be held — a stock, an ETF, a mutual fund, cash.
_Avoid_: asset, instrument, stock (unqualified)

**Holding**:
How much of one Security an Account holds right now. A snapshot of the present, never a history.
_Avoid_: position, lot

**Cost basis**:
What the owner paid for a Holding. Often not reported by Canadian brokerages, in which case gain is unknown rather than zero.
_Avoid_: book value, purchase price

**Trade**:
One buy, sell, dividend, fee, or transfer on an investing Account.
_Avoid_: investment transaction, order, activity

### Cadence

**Refresh**:
Fetching new and changed Transactions from Plaid for every Item and updating the local store. Triggered by hand from the dashboard, or automatically on a Payday.
_Avoid_: sync, pull, update

**Payday**:
Every second Friday, anchored on 2026-08-21. The day an automatic Refresh runs.
_Avoid_: pay date, cycle
