# Household money is integer cents

Budgeting and investing store money as SQLite `REAL`, which is an 8-byte IEEE float. They only ever sum it — a total that lands on `115.8199999` is rounded once at the end and displayed as `$115.82`, and nothing downstream depends on the difference.

Household is the first domain that *divides* money. Splitting $100 three ways in floats gives three values that do not add back to $100, and the residue does not stay cosmetic: it accumulates across every Share, and the number it corrupts is what one roommate owes another. A budget that is a cent out is a rounding artefact. A ledger that is a cent out is an argument.

Household therefore stores every amount as an integer count of cents and formats only at the edge. Splitting is integer division plus an explicit remainder: `base = total // n`, and the leftover pennies go to the payer first and then in a stable Member order, so the Shares always sum to exactly the total and the allocation is reproducible.

## Consequences

The database holds two money conventions at once, and the boundary between them is the package boundary — `REAL` in `budgeting` and `investing`, `INTEGER` cents in `household`. That is a genuine wart. It is accepted because no value ever crosses the boundary (ADR-0013 rules out any bridge between the contexts), so there is no conversion site where the two could be confused, and because converting the existing domains is a separate change with its own risk that this feature does not need to take on.

Converting the older columns remains worth doing on its own ticket. It gets more expensive the longer it waits, and `REAL` maps awkwardly if the app ever moves to Postgres.

The split maths is pure and lives apart from storage, so the properties that matter are unit-testable without a database: Shares sum to the total in every split mode, and an indivisible total still allocates every penny.

## Considered Options

- **`REAL` throughout, for consistency with the existing domains**: rejected — consistency with a convention that is wrong for this use is not a virtue. The cost lands on the roommate who is owed $899.99.
- **Python `Decimal`**: correct, and a reasonable alternative. Rejected because SQLite has no decimal type, so it would be stored as TEXT and parsed on every read — all the friction of a custom representation without integer cents' simplicity or its cheap arithmetic.
- **Storing the total and computing Shares on read**: rejected — Shares must be individually amendable after a Dispute, so they are facts to be recorded rather than a function of the total.
