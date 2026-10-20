# pythia-postgres

pythia for PostgreSQL: PL/pgSQL development for AI agents, built on
[pythia-core](https://github.com/thaildhe172591/pythia-core). It aims to do
what [pythia](https://github.com/thaildhe172591/pythia) does on Oracle: the
agent learns from the live catalog, asks a person before any write, and
writes only through a gate that snapshots, verifies and reports honestly.

**Pre-alpha (Phase 1).** It reads: an agent can do pythia's whole Learn
movement against a live PostgreSQL. It writes nothing yet. The road and how
each pythia idea maps onto PostgreSQL are in pythia-core's
[DESIGN.md](https://github.com/thaildhe172591/pythia-core/blob/main/DESIGN.md).

| Works today | Next (Phase 2) |
|---|---|
| `check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`, `connections`, `version` | `apply` with a verified preview: run, verify, roll back, then ask |

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

Every command opens a read-only session: PostgreSQL itself refuses a write
in it.

```bash
pythia-pg check                  # server, database, schema, search_path drift
pythia-pg ls "t_order%"          # objects by LIKE pattern, any case
pythia-pg src f_order_total      # source as PostgreSQL prints it, one unit per overload
pythia-pg cols t_order           # columns, defaults, comments
pythia-pg ddl t_order            # CREATE statement: tables rebuilt from the catalog
pythia-pg grep "t_order where"   # every source line holding a text
pythia-pg deps f_order_paid      # what it depends on
pythia-pg impact t_order         # what depends on it: run before changing it
pythia-pg errors [NAME]          # plpgsql_check's findings, or why there are none
pythia-pg connections            # entries without their secrets
```

Names fold like PostgreSQL's: `T_ORDER` is `t_order`, `'"MixedCase"'` is
taken exactly. `--json` gives one envelope per command. `--limit`,
`--max-lines` and `--offset` window long output, and any truncation says how
to fetch the rest.

### What the catalog cannot see, and how pythia-pg says so

- **`deps` and `impact` ask twice.** `pg_depend` records views,
  materialized views, SQL-standard function bodies (`BEGIN ATOMIC`),
  triggers, constraints, column defaults and policies. It does not see into
  a PL/pgSQL body, or a SQL function whose body is a string. Those are found
  by a whole-word search of function source and marked `[text]`: a lead, not
  a proof. Every run prints these blind spots: names built at run time
  (`EXECUTE format(...)`), and other databases and servers.
- **`impact` says when to stop.** At 10 or more dependents, or any in
  another schema, it says to show the list to the developer before writing
  code.
- **`errors` never reads as clean when it is not.** PostgreSQL checks only
  syntax when a PL/pgSQL function is created. Without the `plpgsql_check`
  extension, `errors` prints `NOT VERIFIED` and says how to add it. With the
  extension, unqualified names are resolved with the configured schema first
  on `search_path`, as the schema's application would. If the account has no
  `USAGE` on the schema, `errors` reports nothing and names the `GRANT`
  needed. Without `USAGE`, every name would look missing.
- **`ddl` of a table is rebuilt, not dumped.** It is rebuilt from the
  catalog: columns, identity, generated columns, constraints, indexes,
  triggers and comments. The test suite proves the round trip: drop the
  table, run the DDL, rebuild it, compare. `pg_dump --schema-only` stays the
  reference for anything it does not cover yet, and the output says which.

### Least privilege

The read commands need only `LOGIN`: PostgreSQL's catalog is readable by
every role. `errors` also needs `USAGE` on the schema. Exit codes follow
pythia: `0` clean, `1` refused, with the reason and the next step.

## Tests

```bash
python tests/test_postgres.py   # no database, no psycopg: a stand-in catalog answers by query file
python tests/live_check.py      # a disposable server only (see its docstring)
```

`test_postgres.py` finds pythia-core installed, in a checkout next to this
one (`../pythia-core`), or at `PYTHIA_CORE_SRC`. CI runs it on Ubuntu,
Windows and macOS, Python 3.9 and 3.13. CI also runs the live check against
a `postgres:16` service container. The live check loads
[tests/fixtures/app_owner.sql](tests/fixtures/app_owner.sql) and checks
every command against it, `errors` with and without `plpgsql_check`.
While pythia-core is private, CI needs a `PYTHIA_CORE_TOKEN` secret that can
read it. CI tests against the pythia-core branch of the same name when one
exists, so a change spanning both repositories is tested whole.

## License

MIT
