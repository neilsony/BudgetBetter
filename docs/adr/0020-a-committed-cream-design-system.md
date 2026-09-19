# A committed cream design system, served from /static

The CSS grew one page at a time: 382 lines inlined across thirteen templates, two-thirds of it duplicated table, tile, badge and field boilerplate that had already drifted. `.greyed` was `0.5` in one template and `0.55` in three others. `select` had three different paddings. The same stat tile existed twice under two different class names — `.tile .label/.value` on the Plaid pages, `.tile .k/.v` on the Household ones. There was no stylesheet to put a fix in.

It is now one stylesheet, `static/css/app.css`, with design tokens and a shared component layer. Every page-level `<style>` block is gone, and a test asserts none comes back.

The visual direction is editorial/terminal: a warm cream ground, monospace throughout, one vermillion accent, square bordered cards, black bars as card headers, and tiny uppercase letter-spaced micro-labels. Money is set in oversized tabular numerals, because a ledger's numbers are the thing people came to read.

## Three decisions worth recording

**Static files are served, and there is still no build step.** ADR-0006 committed to server-rendered HTML with no build. That still holds — there is no bundler, no transpilation, no `node_modules`. A stylesheet, three scripts and a font file served from `/static` are not a build; they are the alternative to pasting the same CSS into thirteen files. The mount is four lines in `app.py`.

**Dark mode was removed, not forgotten.** The app carried a full `prefers-color-scheme: dark` palette. The cream ground is the identity of this design, and a dark variant would not have been the same design in another skin — it would have been a second design to keep in step, doubling every colour decision and every contrast check. Dark is now used as a *device* instead: the brand block, the card-header bars, the active nav item. Every colour is still a `--` token on a single `:root`, so a dark palette remains a drop-in if it is ever wanted.

**Money formatting was unified.** Household stored integer cents and rendered `$1,025.00` through its `money` filter; budgeting and investing stored floats and rendered `$1425.00` through `'%.2f'|format(...)` across 27 sites. A design system built on tabular numerals cannot ship two money formats. `templating.dollars` now formats floats by delegating to the same `money` function, so both domains produce identical output. Two tests moved with it.

## Consequences

**Uppercase is applied in CSS, never typed into the markup.** Labels stay sentence-case in the HTML — `Total spending`, `You owe`, `Trade history` — and `text-transform` capitalises them. That is not only a screen-reader and copy-paste win: it is why a redesign that rewrote all thirteen templates broke only three of the fifteen assertions that read rendered HTML.

**One test had to be rewritten rather than preserved.** `test_the_refresh_confirmation_is_hidden_until_the_button_is_clicked` asserted the literal string `[hidden] { display: none !important; }` appeared in the response, which an external stylesheet fails by construction. It was pinning implementation, not behaviour. It now asserts the stylesheet and script are linked, and a second test checks the rule is actually present in the served CSS — because three scripts drive visibility through the `hidden` attribute and break silently without it.

**The accent cannot be used for small text.** `--accent` on `--paper` is about 4.3:1, which fails WCAG AA for body copy. `--accent-deep` (~6:1) exists for that, and the rule is written at the top of the stylesheet: accent for fills and text 24px and over, accent-deep for anything smaller.

**The font is self-hosted.** Two weights of JetBrains Mono, latin subset, 43KB total. Deploy is the next piece of work, and a Google Fonts CDN link would have made a webfont the project's first non-Plaid external dependency. The stack falls back to `ui-monospace, SFMono-Regular, Menlo` if it fails to load.

**One script stays inline.** `connect.html`'s Plaid script interpolates `{{ kind }}`, so it is templated JavaScript and has no business in a static file. The two-step-refresh script, previously duplicated byte-for-byte between the budgeting and investing pages, is now `static/js/refresh.js` and included by both.

Two latent bugs were fixed in passing. The old mobile breakpoint hid `.sidebar .foot`, which took the member name *and* the sign-out button with it — on an app six people will mostly use on phones. And table-row buttons were `5px 11px`, far under the 44×44px touch minimum; they now reach 44px under `@media (pointer: coarse)` without bloating the desktop layout.

## Considered Options

- **Keeping the CSS inline and just tidying it**: rejected — the duplication was not an accident of style but of having nowhere else to put shared rules. Without a stylesheet the drift returns.
- **A React or Vite front end**: rejected. Every route would become a JSON endpoint, auth would move from cookie-rendered pages to fetch, and essentially every test would be rewritten — weeks of work, immediately before deploying. Nothing in the target design needs client-side routing or client state.
- **Tailwind via the play CDN**: rejected — it moves the design system into class attributes spread across thirteen templates, which is the problem being solved, and adds a runtime dependency for something plain CSS does here.
- **Keeping dark mode**: see above.
