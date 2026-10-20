---
name: pythia-pg-impact
description: Use before proposing or writing any change to a PostgreSQL object - a function, procedure, trigger, view, table, column or type. Impact analysis comes first, because what depends on an object decides how careful the change must be.
---

# Impact Before Change

**Announce at start:** "Using pythia-pg-impact to measure the blast radius first."

**Phase:** Learn — and the first Ask gate: a large blast radius reaches the developer before any code is written

A dropped column breaks every function that reads it — at call time, not
when the column goes, because PostgreSQL does not record what a PL/pgSQL
body uses. The cost of knowing first is one command.

## The Iron Law

```
NO CHANGE PROPOSED WITHOUT ITS IMPACT MEASURED FIRST
```

## The Workflow

1. `pythia-pg impact <name> --depth 2` — everything that depends on it, as
   a tree, ending with the summary:
   `-- impact: N dependent objects (... matched by name as text ...)`.
2. `pythia-pg deps <name> --depth 2` — the other direction, what it uses;
   read it when the change touches calls or table access.
3. `pythia-pg errors` — the baseline. Anything broken before the change
   must not be blamed on it later.

## Reading the numbers

| Result | What to do |
|---|---|
| 0 dependents | Say so, with the output as evidence, and proceed. |
| 1–9 dependents | List them to the developer alongside the proposal. |
| `! show this list to the developer` (10+, or one in another schema) | Show the tree and get an explicit go-ahead **before writing any code**. |
| `[text]` rows | Leads found by name in function source: name them as such. |
| `-- blind spot:` lines | Relay them. Never call the list complete. |

Overloads count separately: `f_order_total(integer)` and
`f_order_total(integer, boolean)` are two functions, and impact walks each.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "It's just a small helper" | Helpers are the most-depended-on objects there are. |
| "I'll check impact after writing the code" | Then the number cannot change the design. Too late. |
| "The catalog shows no dependents, so nothing calls it" | Function bodies are not in the catalog — read the `[text]` rows and blind spots. |
| "apply's preview shows what breaks anyway" | That confirms a number you should already know; it is not discovery. |

## Hand-off

Impact known and acceptable → write the change (one statement per file) →
`pythia-pg-apply` to land it through the gate.
