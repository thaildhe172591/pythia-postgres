---
name: pythia-pg-verify
description: Use before claiming any PostgreSQL change is done, fixed, working or safe - after an apply, a restore, or a fix to a broken function. Evidence first - exit codes, the checker, the dependents - and "broken" or "not verified" said plainly.
---

# Evidence before "done"

**Announce at start:** "Using pythia-pg-verify — evidence before done."

**Phase:** Do — the last step of every change

PostgreSQL accepts a PL/pgSQL function that references a column that does
not exist; it fails when called. "It applied" is not "it works", and a
claim of done without evidence costs the developer the debugging later.

## The Iron Law

```
NO COMPLETION CLAIM WITHOUT THE EVIDENCE PRINTED IN THIS SESSION
```

## The Checklist

1. **Every write's exit code, unpiped.** 0 clean, 3 written-but-broken.
   A 3 means the report starts with "broken".
2. **`pythia-pg errors <name>`** for each object you touched, and for each
   dependent that `impact` listed. Compare with the baseline taken before
   the change: only new findings are yours.
3. **`NOT VERIFIED` is reported as such.** Without `plpgsql_check`, or for a
   language it cannot read, nothing was checked: say "applied, not
   verified", never "clean".
4. **The dependents.** If the change altered a signature, a column or a
   return type, read the `[text]` rows from `impact` again — they are where
   a call-time failure hides.
5. **The journal.** `pythia-pg history <name>` shows the entry; quote its
   restore command in the report for a change the developer may want back.

## How to report

```
Applied f_order_total (FUNCTION) — exit 0.
errors f_order_total: none (plpgsql_check).
Dependents: v_order_summary [catalog], f_order_paid [text] — errors: none.
Restore if needed: pythia-pg journal restore <entry>
```

Say "broken" first when it is; say "not verified" plainly when it is.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "apply printed Applied" | Read the exit code and the rehearsal lines, not the word. |
| "errors printed nothing" | With no NOT VERIFIED line, that is evidence. With one, it is not. |
| "The dependents compiled before" | PL/pgSQL is checked at call time; check them now. |
| "I'll verify after reporting" | Then the report is a guess. |
