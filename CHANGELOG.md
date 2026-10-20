# Changelog

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
