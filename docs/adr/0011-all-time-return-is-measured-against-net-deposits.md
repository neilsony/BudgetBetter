# All-time return is measured against net deposits

The dashboard's headline return is **total value minus net deposits** — what the account is worth against every dollar ever paid into it. This is the figure Wealthsimple's own app reports, and reproducing it to within four cents ($527.11 against their $527.07) is how we know the definition is right.

The obvious alternative, and what the code did first, is unrealised gain: current value of the Holdings minus their cost basis. That answers a narrower question — how are my *current positions* doing — and on an account with any trading history it is badly wrong as a headline. Against 34 sells totalling $5,572.66 it reported +$176.33 where the broker reported +$527.07, because every gain already realised had vanished from it.

Both are now shown. All-time return leads; unrealised gain sits beside it.

## What counts as a contribution

Only cash crossing the account boundary: `deposit`, `withdrawal`, `contribution`, `transfer`, `send`. Buys and sells move money *within* the account and are excluded — counting a buy as a contribution would make every purchase look like new money.

**Dividends are deliberately not contributions.** A dividend is money the account earned, so it belongs in the return, not the baseline. Treating it as a deposit would silently understate the gain, and it is precisely this distinction that makes our figure agree with the broker's.

## Consequences

The figure depends on having the account's full deposit history. Plaid backfills two years of investment transactions (`INITIAL_BACKFILL_DAYS`), so an account funded earlier than that would show contributions that are too low and a return that is correspondingly too high. The dashboard shows "Not enough history" when no external flow was found at all, but it cannot detect a partial history — worth revisiting if this tool is ever pointed at an older account.
