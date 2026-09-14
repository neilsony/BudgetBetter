# BudgetBetter

A personal budgeting tool and a shared household ledger in one app.

It links the owner's bank through Plaid, pulls their Transactions into a local store, sorts each one into a Bucket, and shows spending on a dashboard. That half is the owner's alone and nobody else ever sees it.

It also keeps a ledger of shared expenses between the owner and their roommates, who each have a login of their own. The two halves share a database and nothing else: no Plaid data reaches the household ledger, and no roommate reaches the banking side.

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

### Household

Nothing in this group touches Plaid. Money here is entered by hand and moves between people, not between Accounts.

**Household**:
The group of people sharing a home and a ledger. There is exactly one.
_Avoid_: group, house (unqualified), team

**Member**:
One person in the Household, with a login of their own. Joins by registering, and is never deleted — a Member who moves out stops appearing in new Expenses but keeps their history.
_Avoid_: user, roommate, tenant, account

**Owner**:
The one Member who administers the Household. The only person who can resolve a Dispute, change the Rent table, or see the banking side of the app at all.
_Avoid_: admin, me, superuser

**Expense**:
Money one Member has already paid that others owe a portion of. Always money already spent — never a request for money not yet laid out.
_Avoid_: request, bill, IOU, charge

**Share**:
One Member's portion of one Expense. The Shares on an Expense sum exactly to its total, and a Share is the only thing that ever moves what someone owes.
_Avoid_: split, portion, debt, line item

**Claim**:
An ower's assertion that they have sent the money for a Share. Clears the Share only once the Expense's payer confirms it, so neither side can settle a debt alone.
_Avoid_: payment, settlement, repayment

**Dispute**:
A Member's objection to their own Share, carrying a reason. While it is open the Share counts against nobody. Only the Owner resolves one, by upholding it, denying it, or amending the Share to a corrected amount.
_Avoid_: complaint, rejection, appeal, contest

**Balance**:
What one Member owes another, derived by netting their Shares in both directions. Only ever between two people — this project never tells anyone to pay someone they did not transact with.
_Avoid_: total (unqualified), debt, owing

**Write-off**:
The Owner forgiving an outstanding Share, usually a departed Member's. Clears what is owed without anyone having paid it.
_Avoid_: cancel, void, forgive

**House PIN**:
The shared secret that lets someone register as a Member. Held by the Owner and changeable by them.
_Avoid_: invite code, password, join code

**Rent**:
The one Expense whose Shares come from a fixed per-Member table rather than being split, raised by a single button. Never disputed and never amended, so the amounts cannot be argued with — only the Owner changes the table.
_Avoid_: lease, monthly, housing
