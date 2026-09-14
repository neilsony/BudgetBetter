# SQLite stays, for a multi-user deployment

ADR-0001 chose SQLite because "BudgetBetter is a single-user tool running on one laptop", and named Postgres as the answer "if this ever became multi-user or hosted". Household makes it both. This records why that trigger is not being honoured, and what is being accepted instead.

The numbers are not close. SQLite allows unlimited concurrent readers and exactly one writer per database file; in WAL mode, which this project already uses, readers and writers no longer block each other. Six people generating on the order of a thousand rows a year sit several orders of magnitude below where that single-writer limit starts to matter — SQLite's own guidance puts the comfortable ceiling around 100,000 hits a day, and sqlite.org itself runs on it.

What SQLite costs is not throughput. It is deployment shape, and that cost is real.

## Consequences

**Exactly one instance, with a persistent local disk, permanently.** WAL requires every process touching the database to share memory through the `-shm` file, which processes on different hosts cannot do. Multiple processes on one machine are fine, so the app can scale vertically, but it can never scale out.

That rules out most of the managed options: Fargate and any container service running more than one task, Lambda, and autoscaled Elastic Beanstalk. **EFS is ruled out too**, and for a sturdier reason than the usual NFS-locking folklore — EFS speaks NFSv4, whose locking is genuinely better than the NFSv3 implementations SQLite's warnings were written against, but the WAL shared-memory requirement makes cross-host access impossible regardless, and a ledger's durability depends on `fsync` meaning what it says. What remains is one EC2 instance with an EBS volume, or Lightsail.

**Blue/green deploys are incompatible with this.** Both colours are live during cutover, which is two writers on a file format that permits one. Deploys are therefore stop-swap-start: a few seconds of downtime for six people.

**Backups matter more than the engine choice**, because the ledger now holds other people's money records. Continuous replication to object storage gives a recovery point of about a second, and is worth strictly more than the difference between SQLite and Postgres here. A restore must be tested before it is trusted.

**The exit trigger is operational, not numeric.** Move to Postgres when a second instance, true zero-downtime deploys, or high availability become requirements. Not for row counts, and not for write volume.

Three things in `core/db.py` have to change before this is safe for six people, and they are recorded here because they are consequences of this decision rather than of Household itself. Every read-modify-write transaction must open with `BEGIN IMMEDIATE`: Python's implicit `BEGIN DEFERRED` starts a read transaction and upgrades it later, and if another connection wrote in between, SQLite returns `SQLITE_BUSY_SNAPSHOT` and deliberately declines to retry, because retrying could deadlock. A busy timeout cannot rescue that. `PRAGMA foreign_keys` must be turned on, since SQLite defaults it off and every `ON DELETE CASCADE` in the schema is otherwise decorative. And `initialise()` must move from the per-request dependency to application startup, because running DDL on every request means many threads contending for the single write lock to do nothing.

## Considered Options

- **Postgres now**: rejected. It would mean rewriting placeholder syntax across all existing SQL, replacing `sqlite3.Row` conversion, and losing the in-memory database the whole test suite is built on — churning working code for capacity that is not needed, and roughly tripling the monthly hosting cost.
- **Aurora Serverless v2 scaled to zero**: rejected. It does now pause to zero compute, but resuming takes fifteen to thirty seconds, which lands on whoever opens the app first each morning.
- **A managed free-tier Postgres**: rejected for money data. The free tiers that would fit either omit automated backups and point-in-time recovery entirely, or pause projects after a week of inactivity.
- **SQLite on EFS to allow more than one instance**: rejected as above, and it is the specific mistake most likely to be made later, so it is written down.
