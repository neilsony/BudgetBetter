-- Tables shared by both domains: the connections themselves, and the accounts
-- hanging off them. See ADR-0001 and ADR-0012.

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
    account_id      TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    official_name   TEXT,
    mask            TEXT,
    type            TEXT NOT NULL,
    subtype         TEXT,
    -- What the broker says the Account is worth, cash included. See ADR-0010.
    current_balance REAL
);
