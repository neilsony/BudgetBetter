# Household is a second bounded context, not a third Plaid domain

ADR-0008 added investing beside budgeting on the grounds that the two shared the Item, Account and Institution vocabulary but nothing else. Household shares even less: it has no Institution, no Item, no Account, no Transaction, and it never calls Plaid. Its nouns — Member, Expense, Share, Dispute — describe money moving between people rather than money moving through a bank.

It also breaks the assumption the other two were built on. Budgeting and investing exist for one human, the owner, and `CONTEXT.md` said so in its opening line. Household has six people with logins of their own.

So it is a third domain package by the ADR-0012 rule — its own `schema.sql`, `models.py`, `db.py`, its own maths, importing only from `core` and composed in `app.py` — but it is a genuinely separate bounded context that happens to share a process and a database file. The glossary reflects that: Household terms live in their own group, and none of them are defined in terms of Plaid.

## Consequences

`core` grows the notion of a Member and a session, because identity is the one thing both halves need: budgeting needs it to know it is talking to the owner, and Household needs it for every row it writes. Identity is therefore built in full for v1 even though only one person will use the app at first — retrofitting an actor column onto a money ledger after it holds real debts is the expensive version of this change.

Nothing bridges the two contexts in either direction. An Expense's amount is typed in by hand rather than pointed at a Plaid Transaction, and a roommate's e-transfer arriving in the owner's chequing account is a budgeting concern governed by ADR-0004, not a Household one. Bridging would require `household` to import `budgeting`, which ADR-0012 forbids.

## Considered Options

- **A second application**: rejected — two deploys, two databases and two backups to keep the roommate ledger away from bank data, when authorization achieves the same thing (ADR-0014).
- **Modelling roommates as records rather than accounts**, keeping the app single-user: rejected — the whole point is that five other people log in and see what they owe. A roommate who cannot log in is a row in a spreadsheet.
- **Reusing Buckets or Transactions for shared expenses**: rejected for the same reason ADR-0008 rejected reusing Buckets for Holdings. A Share is not spending; it is a claim between two people.
