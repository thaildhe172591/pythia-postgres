# pythia-postgres

pythia for PostgreSQL: PL/pgSQL development for AI agents, built on
[pythia-core](https://github.com/thaildhe172591/pythia-core). It aims to do
what [pythia](https://github.com/thaildhe172591/pythia) does on Oracle: the
agent learns from the live catalog, asks a person before any write, and
writes only through a gate that snapshots, verifies and reports honestly.

**Pre-alpha (Phase 3b).** It reads everything pythia's Learn movement
needs, and it writes through one gate. Every write is rehearsed inside a
transaction, shown, approved by the developer — in the agent's chat or at
their console — and committed only as approved. `pythia-pg install` wires a project for an
agent: a guard that denies `psql` writing around the gate, the rules in
every session, and the `pythia-pg-*` skills. The road and how each pythia idea maps onto
PostgreSQL are in pythia-core's
[DESIGN.md](https://github.com/thaildhe172591/pythia-core/blob/main/DESIGN.md).
What each gate stops, and what it does not, is in its
[SECURITY.md](https://github.com/thaildhe172591/pythia-core/blob/main/SECURITY.md).

| Works today | Next |
|---|---|
| `check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`; `apply`, `approve` (console, chat, MCP), `policy`, `journal`, `history`; `install`, `doctor`, `skill lint`, the hooks, `mcp` | scripts (deploy), lint rules, autopilot leases (3c) |

## Install (from git while pre-alpha)

```bash
pip install "git+https://github.com/thaildhe172591/pythia-core" \
            "git+https://github.com/thaildhe172591/pythia-postgres"
```

That brings psycopg 3 with its own libpq (`psycopg[binary]`), so no
PostgreSQL client needs installing.

## Set up a project for an agent

```bash
cd your-project
pythia-pg install     # once; a second run changes nothing
pythia-pg doctor      # is everything wired? exit 1 names what is not
```

`install` writes, and leaves everything else as it was:

- `.pythia/postgres/connections.json`, mode 600, created once from the
  template — the developer fills in the passwords; an agent never opens it;
- `.gitignore` lines for that file, this machine's approvals
  (`.pythia/postgres/grants/`) and `.claude/settings.local.json`;
- `.claude/settings.local.json`: the hooks (the guard, the session brief,
  the AskUserQuestion answer), spelled with this interpreter's absolute path
  so they start whether or not a virtual environment is active, and deny
  rules for the engine's files;
- the MCP approver `pythia_pg` (tool `pythia_pg_approve`), in this
  machine's files only: Claude Code's local scope for the project
  (`~/.claude.json`) and Codex's `~/.codex/config.toml`, each when that
  client has run here;
- a `pythia-pg` block in CLAUDE.md and AGENTS.md (pythia for Oracle's block,
  and the developer's own text, are left alone);
- the skills, in `.claude/skills` and `.agents/skills`: `using-pythia-pg`
  (the router), `pythia-pg-explore`, `pythia-pg-impact`, `pythia-pg-apply`,
  `pythia-pg-verify`.

Restart the agent's session after installing, so the hooks load. Each
session then starts with the rules and a `STATE` line (connections, the
write policy). Before every tool call the guard decides:

| The agent runs | The guard |
|---|---|
| `psql` given write SQL, `-f`, `< file`, a pipe, `\i`; `pg_restore` — also behind `docker exec`, `ssh`, `sudo` or `bash -c` | denies: writes go through `pythia-pg apply` |
| an MCP SQL tool given write SQL | denies |
| reading `connections.json`; editing `policy.json`, the journal or a grant; setting `PYTHIA_PG_CI`; calling `grants.mint` from a one-liner | denies |
| a `pythia-pg` read, a preview, `approve --card` | allows without a prompt |
| `apply --confirm <token>` the developer already approved on this connection | allows; apply re-verifies it |
| `psql` reads, `approve`, `--yes`, `policy set`, anything compound | stays out: the client asks |

The guard reads a command for what it names, not what it means: it can
deny a harmless command and miss a write spelled in a way it does not
list. The gate behind it holds either way (pythia-core's SECURITY.md).

## Connections

`.pythia/postgres/connections.json` in the project root, owner-readable only
(`chmod 600`), and out of git — `pythia-pg install` does all three. Template:
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

### Writing: the gate

```bash
pythia-pg apply change.sql                   # preview: rehearsed, rolled back, nothing written
pythia-pg approve 3fa9c1                     # the developer approves (or from chat, below)
pythia-pg apply change.sql --confirm 3fa9c1  # writes it — only as approved
pythia-pg journal restore <entry>            # undo is a write too: preview, approve, confirm
pythia-pg policy                             # which groups may be written, and is rollback real?
```

The developer approves through the first door that works:

1. **In Claude Code's chat.** The agent asks with AskUserQuestion, its text
   exactly the output of `pythia-pg approve --card <token>`, options
   Approve / Reject. The answer hook records the approval only when the
   question carried that card and the developer chose Approve themselves —
   not an answer the agent wrote, not a dialog that closed unattended.
2. **Through the MCP approver** (`pythia_pg_approve`; Codex starts here):
   the client shows the card, and only an explicit Approve counts.
3. **At the developer's console:** `pythia-pg approve <token>`.

`pythia-pg doctor` warns about settings that would answer the chat door for
the developer (`dontAsk` mode, an allow rule for AskUserQuestion, a hook
matching every tool).

One statement per file. `apply` sorts it into a group, and the policy
decides: `source` (functions, procedures, views) and `comments` need the
developer's approval; `data_dml`, `structural` and `grants` are denied
until the developer runs `pythia-pg policy set <group> confirm` at a
console. `session` (`SET`) is allowed.

What the preview shows, and why it can be trusted:

- **A rehearsal, not a prediction.** The statement ran inside a transaction
  and was rolled back. The diff compares the definition before and after,
  both as PostgreSQL prints them, so formatting is no noise. With
  `plpgsql_check` installed, it says what the change broke compared with
  just before; an `ALTER TABLE ... DROP COLUMN` names the function it would
  break. Without it, the preview says `NOT VERIFIED`.
- **Overloads are named.** `CREATE OR REPLACE FUNCTION f(int)` next to an
  existing `f(text)` creates a second function; the preview says so.
- **Rows are shown and revalidated.** An UPDATE or DELETE is approved on
  its rows: the count, a sample, and a fingerprint of their ctids. If any
  row joins, leaves or changes before the confirm, the confirm is refused.
- **The confirm is the same rehearsal, committed only if it still
  matches.** Same token (the file, the object as it stood, the rows), same
  row count, and nothing broken that the approved preview did not show.
  Otherwise it rolls back and says what moved.
- **Refused, with the reason:** DO, CALL, SELECT, WITH, transaction
  control, SET ROLE, temporary objects, psql meta-commands, several
  statements in one file, statements that cannot run in a transaction
  (`CREATE INDEX CONCURRENTLY`, `VACUUM`, ...), and an unqualified name that
  `search_path` would send to another schema than the configured one.

A rehearsal is bounded (`statement_timeout` 30 s, `lock_timeout` 5 s). It
still runs triggers and advances sequences, and the preview of a DML
statement says so. Exit codes follow pythia: `0` clean, `1` refused,
`3` written but broken (with the restore command).

### Least privilege

The read commands need only `LOGIN`: PostgreSQL's catalog is readable by
every role. `errors` also needs `USAGE` on the schema. Writing needs what
the statement needs (to replace a function, owning it), and the preview
warns when the account is a superuser, can create roles, or owns the
schema. Set the agent role's search path to the schema it works in:
`ALTER ROLE app_agent IN DATABASE app SET search_path = app_owner, public`.

## Tests

```bash
python tests/test_postgres.py   # no database, no psycopg: a stand-in catalog answers by query file; the statement reader; the guard's patterns; the skills
python tests/live_check.py      # a disposable server only (see its docstring)
```

`test_postgres.py` finds pythia-core installed, in a checkout next to this
one (`../pythia-core`), or at `PYTHIA_CORE_SRC`. CI runs it on Ubuntu,
Windows and macOS, Python 3.9 and 3.13. CI also runs the live check against
a `postgres:16` service container. The live check loads
[tests/fixtures/app_owner.sql](tests/fixtures/app_owner.sql) and checks
every command against it: the reads, then the write gate end to end
(preview, approve, confirm, restore, rows and verifications that moved).
All of it runs with and without `plpgsql_check`.
While pythia-core is private, CI needs a `PYTHIA_CORE_TOKEN` secret that can
read it. CI tests against the pythia-core branch of the same name when one
exists, so a change spanning both repositories is tested whole.

## License

MIT
