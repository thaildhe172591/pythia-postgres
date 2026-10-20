# Working in this repository / with this tool

pythia-postgres is pythia for PostgreSQL, on pythia-core. It is pre-alpha:
read-only, connect-and-check only.

## Using pythia-pg as an agent (Phase 0)

1. **It writes nothing yet, so neither do you through it.** Until `apply`
   exists (Phase 2), propose a change as a file and let the developer run
   it. Never write through `psql` or a driver script on pythia-pg's behalf.
2. **Never open `.pythia/postgres/connections.json`.** It holds passwords.
   `pythia-pg connections` lists the names, users, schemas and targets
   without them.
3. **Exit codes are the verdict:** `0` clean, `1` refused. Relay the reason;
   do not route around it. Never read `$?` through a pipe.
4. **Ask the database, never the dump**, as with pythia: `pythia-pg check`
   says where unqualified names really land.

## Changing pythia-postgres itself

- Run the suite before calling a change done: `python tests/test_postgres.py`
  (no database, no psycopg). Against a disposable server, also
  `python tests/live_check.py`. TDD: the failing test comes first.
- CI runs Ubuntu, Windows and macOS on Python 3.9 and 3.13: build paths with
  `pathlib` / `os.path.join`, and use no stdlib API newer than 3.9.
- **Queries:** every SQL statement lives in `src/pythia_postgres/queries/`,
  one per file, pyformat binds only (`%(s)s`), a literal `%` written `%%`,
  the `-- Purpose / -- Binds / -- Returns` header, and an entry in
  `QUERY_BINDS`.
- **Dependencies:** pythia-core and psycopg, nothing else (a test enforces
  it).
- **Engine-neutral logic goes to pythia-core.** If an answer would be the
  same on SQL Server or MongoDB, it does not belong here (DESIGN.md §3).
- **Docs never contradict code:** a behaviour change updates the docstring,
  README.md and CHANGELOG.md in the same change.
- **Versions** agree in pyproject.toml and `pythia_postgres.__version__`.

## Never

- Read or write pythia for Oracle's files (`.pythia/connections.json`,
  `.pythia/journal/`), or take its `pythia` command or `PYTHIA_*` variables.
- Point the live check at a shared database.
- Put real-world identifiers anywhere (hosts, schemas, tenants,
  credentials). Examples use APP_OWNER, PKG_ORDER, T_ORDER. Everything
  shipped is English.
