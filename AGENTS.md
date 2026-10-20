# Working in this repository / with this tool

pythia-postgres is pythia for PostgreSQL, on pythia-core. It is pre-alpha:
it reads everything pythia's Learn movement needs, and writes through one
gate. `pythia-pg install` wires a project: the guard, the session brief and
the `pythia-pg-*` skills (`using-pythia-pg` routes).

## Using pythia-pg as an agent (Phase 3c)

1. **Ask the database, never the dump.** `ls`, `src`, `cols`, `ddl`, `grep`
   against the live schema; `check` says where unqualified names really
   land.
2. **Impact before change.** Run `pythia-pg impact <NAME>` before proposing
   any modification. When it prints `! show this list to the developer`
   (10 or more dependents, or one in another schema), show the developer
   the list before writing code. Rows marked `[text]` are leads found by
   name in function source, not proofs. Relay the `blind spot` lines, and
   never call an impact list complete.
3. **Writes go through `pythia-pg apply` (one statement per file) or
   `pythia-pg deploy` (a release, one transaction) only.**
   Never write through `psql`, a driver script or another tool: those have
   no snapshot, no rehearsal and no journal. Where `pythia-pg install` wired
   the hooks, the guard denies them; where it did not, this rule still
   binds. No `STATE` line at session start means the hooks are not
   running: say so, and ask the developer to run `pythia-pg doctor`.
4. **The developer sees every preview.** Relay `apply`'s preview verbatim:
   the diff, the rehearsal (what broke, or NOT VERIFIED), the rows, the
   overload and destructive warnings. Then ask through the first door that
   works, moving to the next unasked when one fails: on Claude Code an
   `AskUserQuestion` whose text is the output of `pythia-pg approve --card
   <token>` verbatim (options Approve / Reject); then the
   `pythia_pg_approve` tool (MCP — where Codex starts); then the
   developer's terminal, `pythia-pg approve <token>`. Pass
   `--confirm <token>` only after the approval arrives. `--yes` and
   loosening `policy` are the developer's actions, at a console.
5. **Scope is what was asked.** Dependents that break are reported with a
   proposal, never fixed on your own initiative.
6. **Exit codes are the verdict:** `0` clean · `1` refused (relay the
   reason; do not route around it) · `3` written but broken — never report
   success; show the errors and the printed restore command. Never read
   `$?` through a pipe.
7. **Restores are writes.** `journal restore` previews and needs the same
   approval as any apply.
8. **"Not verified" is said plainly.** `errors` or a rehearsal printing
   `NOT VERIFIED` means nothing was checked there. Never report it as clean.
9. **Truncation is always announced.** If output has no truncation marker,
   you saw everything. If it has one, say so or fetch the rest with
   `--offset`.
10. **Never open `.pythia/postgres/connections.json`, or anything under
    `.pythia/postgres/grants/`.** The first holds passwords;
    `pythia-pg connections` lists what you need. A grant written by anyone
    but `approve` is a forged approval.

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
- **Skills:** `src/pythia_postgres/skills/<name>/SKILL.md`, `name` = folder,
  prefixed `pythia-pg-` (or `using-pythia-pg`), description opening with
  `Use when` / `Use before`, a `**Phase:**` line, at most 150 lines (detail
  in `reference/`), and a row in `using-pythia-pg`'s routing table. A test
  holds every one to it.
- **Docs never contradict code:** a behaviour change updates the docstring,
  README.md, CHANGELOG.md and the affected skill in the same change.
- **Versions** agree in pyproject.toml and `pythia_postgres.__version__`.

## Never

- Read or write pythia for Oracle's files (`.pythia/connections.json`,
  `.pythia/journal/`), or take its `pythia` command or `PYTHIA_*` variables.
- Point the live check at a shared database.
- Put real-world identifiers anywhere (hosts, schemas, tenants,
  credentials). Examples use APP_OWNER, PKG_ORDER, T_ORDER. Everything
  shipped is English.
