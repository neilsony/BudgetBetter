-- BudgetBetter local store. See ADR-0001.

CREATE TABLE IF NOT EXISTS items (
    item_id                TEXT PRIMARY KEY,
    institution_id         TEXT,
    institution_name       TEXT,
    access_token_encrypted TEXT NOT NULL,
    sync_cursor            TEXT,
    created_at             TEXT NOT NULL,
    last_refreshed_at      TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id    TEXT PRIMARY KEY,
    item_id       TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    official_name TEXT,
    mask          TEXT,
    type          TEXT NOT NULL,
    subtype       TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id  TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL,
    date            TEXT NOT NULL,
    name            TEXT NOT NULL,
    merchant_name   TEXT,
    amount          REAL NOT NULL,
    pending         INTEGER NOT NULL DEFAULT 0,
    plaid_primary   TEXT,
    plaid_detailed  TEXT,
    bucket          TEXT NOT NULL DEFAULT 'other',
    -- An Override is set by hand and is never touched by a Refresh. ADR-0003.
    override_bucket TEXT
);

CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions (date);
CREATE INDEX IF NOT EXISTS idx_transactions_bucket ON transactions (bucket);
CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions (account_id);

CREATE TABLE IF NOT EXISTS rules (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind    TEXT NOT NULL CHECK (kind IN ('merchant', 'plaid_category')),
    pattern TEXT NOT NULL,
    bucket  TEXT NOT NULL,
    UNIQUE (kind, pattern)
);
