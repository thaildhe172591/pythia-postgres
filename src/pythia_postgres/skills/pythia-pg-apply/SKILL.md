---
name: pythia-pg-apply
description: Use when landing any change in PostgreSQL - creating or replacing a function, procedure, view or trigger, a COMMENT ON, DDL, a GRANT, an INSERT/UPDATE/DELETE, or restoring a previous version. Every write goes through pythia-pg apply - one statement, rehearsed, previewed, approved by the developer, then committed.
---

# Apply through the gate

**Announce at start:** "Using pythia-pg-apply — preview first, then the developer approves."

**Phase:** Ask → Do — the preview is the Ask, the confirm is the Do

PostgreSQL runs DDL inside a transaction, so pythia-pg rehearses every
statement for real — runs it, checks what broke, rolls it back — and shows
the developer the result before anything is kept. psql, a driver script or
an MCP SQL tool would write with no snapshot, no rehearsal and no journal;
the guard denies them.

## The Iron Law

```
NO WRITE WITHOUT A PREVIEW THE DEVELOPER SAW AND APPROVED
```

## The Workflow

1. **Impact first** (`pythia-pg-impact`) — the number was known before the
   code was written.
2. **One statement per file.** `CREATE OR REPLACE FUNCTION ...;` in its own
   `.sql` file. Several statements, DO blocks, CALL, psql meta-commands and
   anything that cannot run in a transaction are refused — see
   `reference/refusals.md` for each refusal and its way forward.
3. **Preview:** `pythia-pg apply change.sql`. Nothing is kept. It prints:
   - the diff of the definition before and after, as PostgreSQL prints both;
   - the rehearsal: `nothing broke`, what it **would break**, or
     `NOT VERIFIED` with the reason;
   - the rows a DML statement touched, with a sample;
   - warnings: another overload with the same name, `! DESTRUCTIVE`;
   - a token, and the approval line.
4. **Relay the preview verbatim** — diff, rehearsal, rows, warnings. Do not
   summarise away a broken dependent or a NOT VERIFIED line.
5. **Ask.** The developer approves in their own terminal:
   `pythia-pg approve <token>`. You cannot run it, and must never mint a
   grant or set `PYTHIA_PG_CI` — the guard denies both. Wait for their yes.
6. **Confirm:** `pythia-pg apply change.sql --confirm <token>`. It rehearses
   again and commits only if the file, the object, the rows and the
   verification still match what was approved; otherwise it rolls back and
   names what moved — preview again and get the new token approved.
7. **Verify** (`pythia-pg-verify`) before any "done".

## Exit codes are the verdict

| Exit | Meaning | You say |
|---|---|---|
| 0 | written and verified (or NOT VERIFIED, said plainly) | what landed, and what was not checked |
| 1 | refused, nothing written | the reason, verbatim; never route around it |
| 3 | written **but broken** | "broken" first: the errors and the printed restore command; the developer chooses fix-forward or restore |

Never read the exit code through a pipe: `pythia-pg apply ... | tail` returns
tail's code.

## Policy

`data_dml`, `structural` and `grants` are `deny` by default; `source` and
`comments` need the developer's approval. A deny is relayed with its reason.
`pythia-pg policy` shows the policy and whether rollback is real per group.
Loosening it (`policy set`) and `--yes` are the developer's acts, at a
console — never yours.

## Restore is a write

`pythia-pg history <name>` lists every version the journal holds;
`pythia-pg journal restore <entry>` previews putting one back, and goes
through the same approval and `--confirm <token>`. Only definitions and
comments have a restore: rows, a dropped column or a revoked grant do not
come back.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "It's a one-line fix, psql is faster" | Faster to write, and the only copy of what it replaced is gone. |
| "The developer said go ahead earlier" | They approve a token, after seeing its preview. |
| "Exit 3, but it mostly worked" | Exit 3 is broken. Say so first. |
| "I'll split the script and apply each part quietly" | Each part is previewed and approved on its own. |
| "The preview is long, I'll summarise" | The developer approves what they saw. Relay it. |
