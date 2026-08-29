# Access tokens are encrypted at rest with a key in .env

An Item's Plaid access token is long-lived and grants read access to real bank data, so it is stored Fernet-encrypted (via `cryptography`) in the `items` table, with the key held in a gitignored `.env` as `APP_ENCRYPTION_KEY`. The rest of the database — Accounts, Transactions, Rules — stays plaintext, gitignored, and protected at rest by FileVault.

## Consequences

The key and the ciphertext live on the same machine, so this defends against the token leaking through a copied database file, a backup, or an accidental commit — not against an attacker who already has the user's filesystem. Losing `.env` means re-linking the Item through Plaid Link, which is a minute of work, not data loss.

## Considered Options

- **macOS Keychain via `keyring`**: stronger, since the key never sits in a file, but ties the project to macOS and prompts on access.
- **SQLCipher whole-database encryption**: encrypts merchant names and amounts too, at the cost of a native dependency and a passphrase to supply on every run.
- **Plaintext token**: rejected — a token in a stray file copy is a live credential to a real bank.
