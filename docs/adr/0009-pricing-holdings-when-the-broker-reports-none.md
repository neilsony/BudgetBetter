# Pricing Holdings when the broker reports none

Wealthsimple returns `institution_price` and `institution_value` as **`0`, not `null`**, for every Holding. A null check therefore passed, every Holding was valued at zero, and the dashboard reported a 100% loss on a portfolio that was slightly up.

A Holding's price is now resolved in order: the broker's `institution_value`, then its `institution_price`, then the Security's `close_price`. A zero counts as "not reported" at every step, because no real position is worth exactly nothing.

## Consequences

Most values shown are derived from the Security's **last close**, not a live quote, so they move only once a day and can disagree with what the broker's own app shows intraday. The holdings table marks those prices "close" with their date rather than presenting them as live.

When nothing can price a Holding, its cost basis is excluded from the portfolio totals as well as its value. Including the basis alone would report the position as a total loss, which is worse than admitting the value is unknown — the page says how many positions were left out. One real position (BCE.TO) is in this state today.

## Considered Options

- **Trusting `institution_value` alone**: what the code did first, and the bug.
- **Fetching live quotes from a market data API**: accurate intraday, but adds a second vendor, an API key, and rate limits to a tool that only needs a daily figure.
