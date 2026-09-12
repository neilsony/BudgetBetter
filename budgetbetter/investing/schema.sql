-- Investing: Securities, the Holdings that reference them, and trade history.
-- See ADR-0008 and ADR-0012.

CREATE TABLE IF NOT EXISTS securities (
    security_id       TEXT PRIMARY KEY,
    name              TEXT,
    ticker_symbol     TEXT,
    type              TEXT,
    close_price       REAL,
    close_price_as_of TEXT,
    iso_currency_code TEXT
);

-- A Holding is a snapshot of what is held right now, so a Refresh replaces
-- every row for the Item rather than accumulating history. See ADR-0008.
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
