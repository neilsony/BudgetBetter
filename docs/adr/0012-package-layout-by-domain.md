# Package layout follows the domains, not the layers

The code is split into `core/`, `budgeting/` and `investing/`. Each domain owns its whole vertical — its nouns, its tables, its Plaid calls, its maths — so a change to how spending works touches one directory, and the boundary between the two halves is visible in the file tree instead of only in the reader's head.

`core/` holds what genuinely serves both: the SQLite connection, the Item and Account tables, settings, encryption, and the Plaid client plus the calls that are the same whichever product is being linked.

## The dependency rule

**`core` never imports from `budgeting` or `investing`, and those two never import each other.** Both depend on `core`; nothing depends on them except `app.py`, which composes the two into one web app.

Two places bend to keep that true. `core.db.SCHEMA_PATHS` lists each domain's `schema.sql` as a *path* rather than importing the domains. And `core.db.initialise` imports the seed Rules inside the function body, not at module scope, because seeding is the one thing core does that is genuinely budgeting's business.

## Consequences

Call sites name which store they mean — `db.upsert_account` for the shared one, `budgeting_db.list_transactions`, `investing_db.list_holdings`. That is more verbose than a single `db` module, and deliberately so: the previous single `db.py` had grown to 488 lines covering both domains, and nothing in a call site said which half you were touching.

Each domain's tables live in its own `schema.sql`, all applied by `core.db.initialise` against the one database. Migrations stay central in `core.db._migrate`, since they run before any domain code and must not depend on it.
