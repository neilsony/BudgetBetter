# SQLite as the local store

BudgetBetter is a single-user tool running on one laptop, so we store Items, Accounts, Transactions and Rules in one SQLite file (`budgetbetter.db`) through the stdlib `sqlite3` module. It needs no server to install or run, gives us real transactions and SQL for the dashboard aggregates, and comfortably holds a couple of decades of personal Transactions.

## Considered Options

- **Flat JSON/CSV files**: trivial to write, but every dashboard total becomes hand-rolled aggregation code.
- **Postgres**: the right answer if this ever became multi-user or hosted, but a daemon to install and run for a tool only one person opens.
- **DuckDB**: excellent at the analytics half, weaker at the frequent small upserts a Refresh performs.
