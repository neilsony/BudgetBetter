# Cursor-based Refresh via /transactions/sync

A Refresh calls Plaid's `/transactions/sync` and stores the returned cursor per Item, rather than calling `/transactions/get` over a date range. Plaid then hands us explicit `added` / `modified` / `removed` sets, which is what makes a Refresh idempotent and lets pending Transactions correctly become posted ones without us diffing anything ourselves.

## Consequences

The cursor is the sync state: losing it means a full re-pull, and storing a stale one means silently missing Transactions. It lives in the `items` table and is only advanced after the page it describes has been committed, so a crash mid-Refresh re-fetches that page rather than skipping it.

## Considered Options

- **`/transactions/get` with a date range**: needs us to pick a re-fetch window, and reconciling pending-to-posted transitions inside that window becomes our problem.
