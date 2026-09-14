# BudgetBetter

Personal budgeting tool built on the Plaid API.

## Agent skills

### Issue tracker

Issues and specs are tracked in **GitHub Issues** (`gh` CLI) on `neilsony/BudgetBetter`. See `docs/agents/issue-tracker.md`.

### Domain docs

**Single-context**: `CONTEXT.md` + `docs/adr/` at the repo root, created lazily by `/domain-modeling`. See `docs/agents/domain.md`.

I'm working on BudgetBetter, a personal budgeting + investment tracker at
~/Desktop/BudgetBetter. Before we start, read these in order:

  CONTEXT.md          — the glossary. Use these exact terms (Item, Account,
                        Bucket, Holding, Security, Refresh, Payday).
  docs/adr/           — 12 ADRs. Read 0008–0012 at minimum; they cover the
                        investing half and the package layout.
  README.md           — setup, how to run, module map.

## What it is
Single-user local web app. Python 3.13 + FastAPI + Jinja2 + SQLite, no build
step and no frontend framework (ADR-0006). Plaid is the data source. Two tabs
behind a sidebar: Budgeting (bank spending, sorted into Buckets) and
Investments (Wealthsimple holdings, trades, returns).

## Layout — the dependency rule matters
budgetbetter/{core,budgeting,investing}/ — each domain owns its models, db,
schema.sql and Plaid calls. `core` never imports from the domains; the two
domains never import each other. Only app.py composes them. See ADR-0012.

Call sites name their store: `db.*` (core), `budgeting_db.*`, `investing_db.*`.

## Running it
./run.sh                        → http://localhost:8000 (uvicorn, --reload)
.venv/bin/python -m pytest      → 114 tests, all passing

The server must be running for me to see anything — VS Code Live Server CANNOT
serve this app (it needs the Python process for the Plaid token exchange).
Settings are cached at startup, so restart after editing .env.

## How I want you to work
- Never run `git commit` or `git push`. Give me the message and the staging
  list; I run it. Never add Co-Authored-By.
- Never read .env. There's a deny rule in .claude/settings.json, but don't
  route around it with python/grep either. Ask me to check values instead.
- TDD at seams for logic (see the tests/ layout). Run the full suite before
  telling me something works.
- When a decision is hard to reverse and non-obvious, write an ADR.

## Current state / blockers
- Plaid is in PRODUCTION. Investments product is enabled; Transactions works.
- RBC is NOT linked — Plaid rejects its MFA method ("account settings are
  incompatible"). Support ticket open. So the Budgeting tab has no real data yet.
- Wealthsimple IS linked and working: ~$13k, 21 holdings, 167 trades.
- One holding (BCE.TO) has no price — Plaid returns a near-empty security
  record for it. Not our bug; see ADR-0009.



