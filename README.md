# BudgetBetter

Personal budgeting tool built on the Plaid API. Links your bank, pulls your
transactions into a local SQLite file, sorts them into your own categories, and
shows them on a dashboard that runs on your laptop.

## Setup

```bash
cp .env.example .env
./run.sh                       # creates .venv and installs dependencies
```

Fill in `.env` before the app will do anything:

| Setting | Where it comes from |
| --- | --- |
| `PLAID_CLIENT_ID`, `PLAID_SECRET` | [Plaid dashboard → Keys](https://dashboard.plaid.com/developers/keys) |
| `PLAID_ENV` | `sandbox` while building, `production` for your real bank |
| `APP_ENCRYPTION_KEY` | `python -m budgetbetter.crypto keygen` |

Then open <http://localhost:8000>, connect a bank, and hit **Refresh**.

In Sandbox, sign in to any test bank with `user_good` / `pass_good`. Real RBC
accounts need `PLAID_ENV=production` and a Production access request on the
Plaid dashboard.

## Automatic refresh

A Refresh happens when you click the button, and automatically at noon on every
second Friday (anchored on 2026-08-21). To install the scheduled job:

```bash
sed "s|__PROJECT_DIR__|$PWD|g" scripts/com.budgetbetter.autosync.plist \
  > ~/Library/LaunchAgents/com.budgetbetter.autosync.plist
launchctl load ~/Library/LaunchAgents/com.budgetbetter.autosync.plist
```

Force one by hand with `.venv/bin/python -m budgetbetter.autosync --force`.

## Tests

```bash
.venv/bin/python -m pytest
```

## How it fits together

Each domain owns its whole vertical — nouns, tables, Plaid calls and maths.
`core` serves both and depends on neither. See [ADR-0012](docs/adr/0012-package-layout-by-domain.md).

```
budgetbetter/
├── app.py                  The web app: sidebar, both dashboards, Refresh
├── config.py, crypto.py    Settings from .env, and token encryption
├── core/                   Shared: connection, Items, Accounts, Plaid client
│   ├── db.py  models.py  plaid_client.py  schema.sql
├── budgeting/              Spending
│   ├── sync.py             Pages through /transactions/sync, idempotently
│   ├── categorize.py       Plaid category → your Bucket
│   ├── buckets.py          The Bucket vocabulary and seed Rules
│   ├── analytics.py        Category tiles and the trend chart
│   ├── schedule.py         The payday cadence
│   ├── autosync.py         The launchd entry point
│   └── db.py  models.py  plaid.py  schema.sql
└── investing/              Holdings and trades
    ├── sync.py             Holdings snapshot + trade history
    ├── portfolio.py        Value, cash, all-time return, allocation
    └── db.py  models.py  plaid.py  schema.sql
```

`CONTEXT.md` defines the vocabulary; `docs/adr/` records why things are the way
they are.
