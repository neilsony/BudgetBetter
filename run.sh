#!/usr/bin/env bash
# Start BudgetBetter at http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtualenv…"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env — fill in your Plaid keys, then run this again."
  exit 0
fi

exec .venv/bin/uvicorn budgetbetter.app:app --reload --port 8000
