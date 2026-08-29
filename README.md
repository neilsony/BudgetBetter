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

| Module | Job |
| --- | --- |
| `app.py` | The web app: Connect, Dashboard, Refresh |
| `plaid_client.py` | Every call to Plaid, so nothing else touches the network |
| `sync.py` | Pages through `/transactions/sync` and applies changes idempotently |
| `categorize.py`, `buckets.py` | Turning a Plaid category into one of your Buckets |
| `analytics.py` | The dashboard tiles and the trend chart |
| `db.py`, `schema.sql` | The local SQLite store |
| `schedule.py`, `autosync.py` | The payday cadence |

`CONTEXT.md` defines the vocabulary; `docs/adr/` records why things are the way
they are.
