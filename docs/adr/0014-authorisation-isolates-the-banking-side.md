# Authorisation, not a second database, isolates the banking side

The budgeting and investing sections are built on the owner's actual bank logins. Five roommates now have accounts in the same app. They must never see any of it.

The instinct is to put the household ledger in its own database file so that a bug in roommate-facing code cannot reach bank data. That instinct is worth naming and then rejecting: a second file gives the *feeling* of isolation while the same process, with the same credentials and the same file permissions, still holds both. Anything that can read one can read the other. The separation that actually holds is the one enforced on every request.

So: one database, one process, and every budgeting and investing route requires the caller to be the Owner. Members reach only `/household/*`. The sidebar renders the banking links for nobody else.

## Consequences

`require_owner` is load-bearing security rather than a convenience, so it is tested as such: the suite asserts that a Member requesting `/` or `/investments` is refused, alongside the ordinary behaviour tests. A route added later without it is a data breach, not a bug.

The app gains real session handling for the first time — hashed passwords, cookies marked `httponly` and `samesite`, and CSRF tokens on every form. None of this was needed while the app was one person on `localhost`, and all of it is needed the moment six people reach it over the internet. ADR-0006's plain HTML forms stay, but every one of them now carries a token, derived from the session rather than stored, so it needs no table and dies with the session.

Passwords and the House PIN are hashed with **`hashlib.scrypt` from the standard library**, not argon2. Argon2 is the better primitive, but it means a pinned C extension, and this project deliberately holds itself to stdlib `sqlite3`, vanilla JavaScript and no build step. scrypt is memory-hard, in the standard library, and more than sound for six accounts. Revisit it if this ever holds more than a household.

One database also means one backup covers everything and one restore brings it all back, which matters more now that losing the ledger loses other people's money records and not just the owner's.

## Considered Options

- **A separate SQLite file for Household**: rejected as described above — it constrains nothing that authorisation does not already constrain, and doubles the backup and restore story.
- **A separate application on its own host**: rejected in ADR-0013. Real isolation, real cost, and no threat it defends against that a single `require_owner` dependency does not.
- **Leaving budgeting unauthenticated because it is "just local"**: rejected — the app is being built to deploy. A route that is safe only while nobody else can reach the host stops being safe the day the host is public, and that is exactly the day nobody remembers to check.
