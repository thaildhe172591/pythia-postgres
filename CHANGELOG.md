# Changelog

## 0.3.0.dev0 — unreleased

Phase 2 of the plan in pythia-core's DESIGN.md: the write tier, behind
pythia-core 0.3.0.dev0's gate.

- **`pythia-pg apply` rehearses every write.** The statement runs inside a
  transaction and is verified, then rolled back. The preview shows what
  happened:
  - the definition before and after, as PostgreSQL prints both;
  - what `plpgsql_check` says the change broke, compared with just before;
  - the rows an UPDATE or DELETE touches;
  - a new overload, named as one.

  `apply --confirm` runs it again and commits only what was approved.
- **A reader that knows PostgreSQL's quoting:** `'…'`, `E'…'`, `"…"`,
  `$tag$…$tag$`, nested comments. One statement per file. Refused, each with
  its reason: DO, CALL, SELECT, WITH, transaction control, SET ROLE,
  temporary objects, psql meta-commands, and statements that cannot run in
  a transaction (`CREATE INDEX CONCURRENTLY`, `VACUUM`, ...).
- **Rows are revalidated by ctid.** An UPDATE or DELETE is approved on its
  count and a fingerprint of the rows' ctids, so a row that joined, left or
  was updated meanwhile refuses the confirm. MERGE, joins and subqueries
  are refused, because their row set cannot be shown.
- **Statement text runs exactly as written.** No driver parameters are
  used, so a `%` in a RAISE format or a LIKE pattern stays a `%`.
- **Restores:** the definition a write replaced, a DROP for a new object,
  the previous comment (or NULL). Each is a write through the same gate.
- **Rehearsals are bounded:** `statement_timeout` 30 s, `lock_timeout` 5 s.
- **`ddl` is rebuilt with only `pg_catalog` on search_path**, as pg_dump
  does. Before, a default like `nextval('seq_order')` came out unqualified
  when the schema was on the reader's path, and failed elsewhere. The DDL
  round trip found it.
- **Live check:** preview, approve, confirm and restore on a real server.
  Rows that moved and a verification that moved are both rolled back. A
  `DROP COLUMN` shows the function it would break. All of it runs with and
  without plpgsql_check.

## 0.2.0.dev0 — unreleased

Phase 1 of the plan in pythia-core's DESIGN.md: the read tier. Needs
pythia-core 0.2.0.dev0.

- **`ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`** against
  the live catalog, names folded as PostgreSQL folds them. `src` and `grep`
  number lines the same way: the definition as PostgreSQL prints it back,
  one unit per overload.
- **`deps` and `impact` ask twice.** First `pg_depend`: views,
  materialized views, `BEGIN ATOMIC` bodies, triggers, constraints, column
  defaults, policies. Then a whole-word search of function source for what
  it cannot see: PL/pgSQL bodies, and SQL functions with a string body.
  Those rows are marked `[text]`, and every run names the blind spots: run
  time names and other databases.
- **`ddl` rebuilds a table from the catalog:** columns, identity, generated
  columns, constraints, indexes, triggers, comments, partitions. Views,
  functions and sequences come as PostgreSQL prints them. The live check
  proves the round trip by dropping the table, running the DDL and
  rebuilding it identically.
- **`errors` uses plpgsql_check when it is installed, and says plainly when
  it is not.** Names are resolved with the configured schema first on
  `search_path`, for that transaction only. An account without `USAGE` on
  the schema gets no list and the `GRANT` it needs, instead of every name
  reported missing. Both false-error cases were found against a real server
  while building this.
- **Tests:** a stand-in catalog answers by query file, so the read tier is
  tested without a database. `tests/fixtures/app_owner.sql` holds every
  dependency shape, and `tests/live_check.py` checks each command against
  it. CI does this on a `postgres:16` service container, with
  `plpgsql_check` installed for the run. CI uses the pythia-core branch of
  the same name when one exists.

## 0.1.0.dev0 — unreleased

Phase 0 of the plan in pythia-core's DESIGN.md.

- **`pythia-pg check`** connects through psycopg 3 in a read-only session.
  PostgreSQL itself then refuses any write. The command reports the server
  version, the database, the configured schema and the session's current
  schema, and warns when `search_path` would send an unqualified name
  somewhere else. `--json` gives the standard envelope.
- **`pythia-pg connections`** lists the entries in
  `.pythia/postgres/connections.json` without their passwords.
- **Connect errors name the next step:** wrong password, a refused
  `pg_hba.conf` line, a role without `LOGIN`, a missing database, a full
  server.
- **Queries live in `queries/`** under pythia-core's contract: pyformat
  binds, a header, binds declared in `QUERY_BINDS`.
- **Live check.** `tests/live_check.py` runs `check` against a disposable
  server and proves that the read-only session refuses a write. CI runs it
  against a `postgres:16` service container.
