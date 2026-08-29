# Server-rendered UI, no build step

The dashboard is Jinja2 templates rendered by FastAPI with a little vanilla JavaScript, deliberately with no Node build step, bundler, or frontend framework. Plaid Link is a browser SDK and the token exchange must happen server-side, so a Python process has to serve the page regardless; adding a second toolchain to render two pages would buy nothing yet.

This is expected to be revisited. When the dashboard grows past tiles, a table and a chart, the intended path is a React front end talking to this app's JSON endpoints — the routes are shaped to make that a swap of the view layer, not a rewrite.

## Consequences

A static file server (Live Server, `python -m http.server`) cannot run this app on its own: the token exchange, the encryption key, and the Refresh endpoint all need the FastAPI process. The app is started with `./run.sh` and opened at `http://localhost:8000`.
