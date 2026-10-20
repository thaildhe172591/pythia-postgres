---
name: pythia-pg-explore
description: Use when explaining, investigating or reading PostgreSQL objects - what a function does, where a table is used, why something fails, what a schema holds. Asks the live database through pythia-pg read commands, never a dump or memory.
---

# Explore the live database

**Announce at start:** "Using pythia-pg-explore to read the live database."

**Phase:** Learn — facts from the catalog, before any opinion

A repository's SQL files drift from the database: a function edited in
place, an index added by hand, a view nobody exported. An explanation built
on the dump is an explanation of a database that does not exist.

## The Iron Law

```
EVERY FACT COMES FROM THE LIVE CATALOG, WITH THE COMMAND THAT SHOWED IT
```

## The commands

| Question | Command |
|---|---|
| Where am I, and where do unqualified names land? | `pythia-pg check` |
| Which objects match a name? | `pythia-pg ls "t_order%"` |
| What does this function / view / trigger say? | `pythia-pg src <name>` |
| What columns does this table or view have? | `pythia-pg cols <name>` |
| What statement would create it? | `pythia-pg ddl <name>` |
| Where is this text used in source? | `pythia-pg grep <text>` |
| What does it use? | `pythia-pg deps <name>` |
| What uses it? | `pythia-pg impact <name>` (see `pythia-pg-impact`) |
| What does the checker say is broken? | `pythia-pg errors [<name>]` |

`--json` gives structured output on every command. Line numbers in `src`
are PostgreSQL's own, so they match the line in an error message.

## Reading the output honestly

- **Truncation is announced.** No `-- truncated` line means you saw
  everything. With one, say so, or fetch the rest with `--offset` /
  `--limit 0`.
- **`[text]` rows are leads, not proofs.** PostgreSQL's catalog does not
  record what a PL/pgSQL body calls; pythia-pg finds those by name in the
  source and marks them. Say which rows are which.
- **`-- blind spot:` lines are part of the answer.** Relay them; never call
  a dependency list complete when one is printed.
- **`NOT VERIFIED` means nothing was checked there** (no `plpgsql_check`, or
  a language it cannot read). It is never "no errors".

## Red flags

| Thought | Reality |
|---------|---------|
| "The migration file shows the table" | The database may not. `pythia-pg cols`. |
| "`errors` printed nothing, so it is clean" | Only if no NOT VERIFIED line was printed. |
| "I'll open connections.json to see the host" | Never: `pythia-pg connections` lists it without passwords. |

## Hand-off

Explaining only → done, with the commands quoted. A change follows →
`pythia-pg-impact` before any code is written.
