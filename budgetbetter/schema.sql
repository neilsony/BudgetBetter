-- BudgetBetter local store. See ADR-0001.

CREATE TABLE IF NOT EXISTS items (
    item_id                TEXT PRIMARY KEY,
    institution_id         TEXT,
    institution_name       TEXT,
    access_token_encrypted TEXT NOT NULL,
    sync_cursor            TEXT,
    created_at             TEXT NOT NULL,
    last_refreshed_at      TEXT,
    -- Which Plaid product this Item was linked for: a budgeting Item pulls
    -- Transactions, an investing Item pulls Holdings. See ADR-0008.
    kind                   TEXT NOT NULL DEFAULT 'budgeting'
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

-- Investments. See ADR-0008.

CREATE TABLE IF NOT EXISTS securities (
    security_id       TEXT PRIMARY KEY,
    name              TEXT,
    ticker_symbol     TEXT,
    type              TEXT,
    close_price       REAL,
    iso_currency_code TEXT
);

-- A Holding is a snapshot of what is held right now, so a Refresh replaces
-- every row for the Item rather than accumulating history.
CREATE TABLE IF NOT EXISTS holdings (
    account_id        TEXT NOT NULL,
    security_id       TEXT NOT NULL,
    quantity          REAL NOT NULL,
    institution_price REAL,
    institution_value REAL,
    cost_basis        REAL,
    iso_currency_code TEXT,
    PRIMARY KEY (account_id, security_id)
);

CREATE TABLE IF NOT EXISTS investment_transactions (
    investment_transaction_id TEXT PRIMARY KEY,
    account_id                TEXT NOT NULL,
    security_id               TEXT,
    date                      TEXT NOT NULL,
    name                      TEXT,
    quantity                  REAL,
    amount                    REAL,
    price                     REAL,
    fees                      REAL,
    type                      TEXT,
    subtype                   TEXT,
    iso_currency_code         TEXT
);

CREATE INDEX IF NOT EXISTS idx_holdings_account ON holdings (account_id);
CREATE INDEX IF NOT EXISTS idx_invtxn_date ON investment_transactions (date);
CREATE INDEX IF NOT EXISTS idx_invtxn_account ON investment_transactions (account_id);
