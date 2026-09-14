# Rent comes from a fixed table and cannot be disputed

Every other Expense is typed in and split. Rent is neither. The Shares are unequal, they are the same every month, they are the largest numbers in the ledger, and they are already agreed — so the flow is one button, no amounts entered, Shares copied verbatim from a table the Owner maintains.

Rent is also **never disputed and never amended**. The amounts are settled outside the app, so there is nothing for the app to arbitrate; the only way a rent Share is wrong is if the table is wrong, and the table is the Owner's to fix.

The table is keyed by Member rather than by name, so it survives people coming and going, and it is edited in the UI rather than in code — the amounts change when the household changes, and that should never require a deploy. The button asks who paid, defaulting to whoever pressed it, because the person who fronts the rent may vary.

What it produces is an ordinary Expense. Nothing about Claims, marking paid, the audit trail or the dashboard has a special case for rent; only the Shares arrive differently.

## Consequences

**A wrong rent Share has no in-app repair once anyone has paid.** An Expense locks when its first Share is confirmed paid, and rent cannot be amended — so if an amount is wrong and someone has already settled, the remedy is a corrective Expense posted in the opposite direction. This is the accepted price of a flow with no input to get wrong, and it is written down here because it will be surprising in the moment.

While nothing has been paid, the sender can simply delete the Expense; the Owner corrects the table and it is raised again.

Because pressing the button twice would silently create a second full month of debt, raising rent when one already exists for that month warns and asks for confirmation rather than proceeding.

The feature ships before it is usable. The table cannot be filled in until every Member has registered, so the schema, the flow and the Owner's editor all land now and the button becomes meaningful once the household is fully signed up.

## Considered Options

- **Rent as a normal Expense with custom amounts**: rejected — it is the same six numbers every month, and retyping the largest figures in the ledger twelve times a year is an invitation to a typo that then cannot be corrected.
- **The amounts as a constant in the source**: rejected — changing rent would mean editing code and redeploying, and rent changes for reasons that have nothing to do with software.
- **Allowing Disputes on rent**: rejected — the split is agreed offline, so a dispute would be an argument the app has no standing to settle. Non-disputable amounts are the point.
- **Allowing the Owner to amend a rent Share**: rejected, narrowly. It would soften the locked-Expense edge above, at the cost of making rent amounts negotiable after the fact, which is exactly what the fixed table exists to prevent.
