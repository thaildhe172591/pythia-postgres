# pythia-postgres

pythia for PostgreSQL: PL/pgSQL development for AI agents, built on
[pythia-core](https://github.com/thaildhe172591/pythia-core). It aims to do
what [pythia](https://github.com/thaildhe172591/pythia) does on Oracle: the
agent learns from the live catalog, asks a person before any write, and
writes only through a gate that snapshots, verifies and reports honestly.

**Pre-alpha (Phase 0).** Today it connects and checks; it does not read code
or write anything yet. The road and how each pythia idea maps onto
PostgreSQL are in pythia-core's [DESIGN.md](https://github.com/thaildhe172591/pythia-core/blob/main/DESIGN.md).

| Works today | Next (Phase 1) | Then (Phase 2) |
|---|---|---|
| `pythia-pg check`, `connections`, `version` | `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact` | `apply` with a verified preview: run, verify, roll back, then ask |

## Install (from git while pre-alpha)

```bash
pip install "git+https://github.com/thaildhe172591/pythia-core" \
            "git+https://github.com/thaildhe172591/pythia-postgres"
```

That brings psycopg 3 with its own libpq (`psycopg[binary]`), so no
PostgreSQL client needs installing.

## Connections

`.pythia/postgres/connections.json` in the project root, owner-readable only
(`chmod 600`), and out of git (`.pythia/` in `.gitignore`). Template:
[examples/connections.example.json](examples/connections.example.json).

```json
{
  "default": "dev",
  "dev": { "host": "db-dev", "port": 5432, "dbname": "app",
           "user": "app_agent", "password": "...", "schema": "APP_OWNER" }
}
```

- `host`, `dbname`, `user` are required. With no `password`, libpq's own
  sources apply (`PGPASSWORD`, `~/.pgpass`). `sslmode` and
  `connect_timeout` (seconds, default 10) are optional.
- `schema` is folded to lower case, as PostgreSQL folds an unquoted name;
  the default is `public`. `check` warns when the session's `search_path`
  puts unqualified names somewhere else.
- The entry is picked by `--conn NAME`, then `PYTHIA_PG_CONNECTION`, then
  the only entry, the folder directly under the project root, then
  `"default"`. Anything ambiguous is an error. `PYTHIA_PG_CONFIG` points at
  another file.

**Alongside pythia for Oracle:** pythia keeps its connections in
`.pythia/connections.json`, and pythia-pg never reads that file. Its
command (`pythia-pg`) and its variables (`PYTHIA_PG_*`) never collide with
pythia's either.

## Commands

```bash
pythia-pg check              # read-only session: server, database, schema, search_path drift
pythia-pg check --json       # the same as one JSON envelope
pythia-pg connections        # entries without their secrets
pythia-pg version
```

Exit codes follow pythia: `0` clean, `1` refused (with the reason and the
next step).

## Tests

```bash
python tests/test_postgres.py   # no database, no psycopg: a stand-in driver
python tests/live_check.py      # a disposable server only; skipped unless PYTHIA_PG_LIVE_HOST is set
```

`test_postgres.py` finds pythia-core installed, in a checkout next to this
one (`../pythia-core`), or at `PYTHIA_CORE_SRC`. CI runs it on Ubuntu,
Windows and macOS, Python 3.9 and 3.13. CI also runs the live check against
a `postgres:16` service container. While pythia-core is private, CI needs a
`PYTHIA_CORE_TOKEN` secret that can read it.

## License

MIT
