-- The shared ledger: Members, the Expenses between them, and the Shares that
-- are the only thing ever moving a Balance. Nothing here touches Plaid.
-- See ADR-0013.
--
-- Money is an integer count of cents, not REAL — this is the one domain that
-- divides money rather than only summing it. See ADR-0015.
-- Dates and timestamps are ISO-8601 TEXT, as everywhere else in this project.

CREATE TABLE IF NOT EXISTS members (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    -- The Owner administers the Household and is the only one who sees the
    -- banking side of the app at all. See ADR-0014.
    role          TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'member')),
    joined_on     TEXT NOT NULL,
    -- Set when a Member moves out. They keep their history and stay named on
    -- live Shares, but join no new Expense. Members are never deleted.
    left_on       TEXT,
    created_at    TEXT NOT NULL
);

-- Single row. Holds the House PIN that gates registration.
CREATE TABLE IF NOT EXISTS house_settings (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    pin_hash   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- The fixed per-Member Rent amounts. Keyed by Member rather than name so it
-- survives people coming and going, and edited by the Owner in the UI rather
-- than in source. See ADR-0019.
CREATE TABLE IF NOT EXISTS rent_shares (
    member_id    INTEGER PRIMARY KEY REFERENCES members(id),
    amount_cents INTEGER NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expenses (
    id                INTEGER PRIMARY KEY,
    -- Who is owed the money. May differ from who entered it: the Rent button
    -- asks who actually paid the landlord.
    payer_id          INTEGER NOT NULL REFERENCES members(id),
    created_by        INTEGER NOT NULL REFERENCES members(id),
    description       TEXT NOT NULL,
    total_cents       INTEGER NOT NULL,
    kind              TEXT NOT NULL DEFAULT 'general'
                      CHECK (kind IN ('general', 'rent', 'dispute_resolution')),
    split_mode        TEXT NOT NULL
                      CHECK (split_mode IN ('equal_all', 'equal_selected', 'custom',
                                            'reimbursement', 'rent', 'resolution')),
    -- Set on a dispute_resolution Expense: the Expense whose upheld Dispute
    -- produced it. See ADR-0017.
    parent_expense_id INTEGER REFERENCES expenses(id),
    incurred_on       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    voided_at         TEXT,
    voided_by         INTEGER REFERENCES members(id)
);

CREATE INDEX IF NOT EXISTS idx_expenses_payer ON expenses(payer_id);
CREATE INDEX IF NOT EXISTS idx_expenses_incurred ON expenses(incurred_on);

CREATE TABLE IF NOT EXISTS shares (
    id           INTEGER PRIMARY KEY,
    expense_id   INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    member_id    INTEGER NOT NULL REFERENCES members(id),
    amount_cents INTEGER NOT NULL,
    -- owed    → counts against the Member, and toward what the payer is owed
    -- claimed → the ower says they have sent it; still counts until confirmed
    -- paid    → cleared
    -- disputed→ counts for nobody while the Dispute is open
    -- void    → an upheld Dispute removed it. See ADR-0016 and ADR-0017.
    status       TEXT NOT NULL DEFAULT 'owed'
                 CHECK (status IN ('owed', 'claimed', 'paid', 'disputed', 'void')),
    claimed_at   TEXT,
    paid_at      TEXT,
    paid_by      INTEGER REFERENCES members(id),
    UNIQUE (expense_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_shares_member ON shares(member_id);
CREATE INDEX IF NOT EXISTS idx_shares_expense ON shares(expense_id);

CREATE TABLE IF NOT EXISTS disputes (
    id                   INTEGER PRIMARY KEY,
    share_id             INTEGER NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    raised_by            INTEGER NOT NULL REFERENCES members(id),
    reason               TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'upheld', 'denied', 'amended')),
    -- Set when the Owner amends rather than upholding outright.
    amended_amount_cents INTEGER,
    resolution_note      TEXT,
    resolved_by          INTEGER REFERENCES members(id),
    raised_at            TEXT NOT NULL,
    resolved_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_disputes_status ON disputes(status);

-- The Owner forgiving an outstanding Share, usually a departed Member's, so a
-- dead debt does not sit on someone's dashboard forever.
CREATE TABLE IF NOT EXISTS write_offs (
    id              INTEGER PRIMARY KEY,
    share_id        INTEGER NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    written_off_by  INTEGER NOT NULL REFERENCES members(id),
    reason          TEXT,
    at              TEXT NOT NULL
);

-- Append-only audit. Every mutation lands here with who did it and the row on
-- either side of the change, so the history stays rich enough to reconstruct
-- from. Nothing in this domain is ever hard-deleted.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    actor_id    INTEGER REFERENCES members(id),
    entity      TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    action      TEXT NOT NULL,
    before_json TEXT,
    after_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity, entity_id);

-- One row per Member per thing they should know about. Rendered in-app now;
-- an email sender drains the same table once this is deployed.
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id),
    event_id   INTEGER REFERENCES events(id),
    kind       TEXT NOT NULL,
    body       TEXT NOT NULL,
    link       TEXT,
    seen_at    TEXT,
    emailed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notifications_member ON notifications(member_id, seen_at);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
