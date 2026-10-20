---
name: using-pythia-pg
description: Use when starting any conversation that touches PostgreSQL, PL/pgSQL, a schema, a function, a trigger or a view - it picks the right pythia-pg skill BEFORE any response or action, including clarifying questions. Fires on plain requests in any language - "build/add/fix/explain/review X", "lam/them/sua/tao/giai thich/kiem tra X" (Vietnamese, with or without diacritics). Also use whenever unsure which pythia-pg skill applies.
---

# Using pythia-pg — the pocket handbook

**Phase:** Learn → Ask → Do — this page opens the right one

pythia-pg is pythia for PostgreSQL. Its one job here is consistency:
whether a session measures the blast radius and asks before it writes
should not depend on the agent's mood that day.

## The Rule

If there is even a small chance a pythia-pg skill applies, open it **before
acting** — before answering, before exploring, before clarifying questions.
Opened the wrong one? Close it, no harm done.

## Route by what the developer said

| The request sounds like | Open first | Then |
|---|---|---|
| "explain X / why / how does it work" ("giải thích") | `pythia-pg-explore` | |
| "is it safe to touch X" | `pythia-pg-impact` | |
| "change / fix / add X" ("sửa", "thêm") | `pythia-pg-impact` | write, then `pythia-pg-apply` |
| "land / apply this" — one statement | `pythia-pg-apply` | `pythia-pg-verify` |
| "run this migration / script / release" ("chạy script") | `pythia-pg-deploy` | `pythia-pg-verify` |
| "do it all without asking me" ("tự động hoàn toàn") | `pythia-pg-autopilot` — one lease, never a blank cheque | the task's own skills |
| "undo / restore X" | `pythia-pg-apply` (a restore is a write) | `pythia-pg-verify` |
| an error from PostgreSQL, a broken function | `pythia-pg-explore` (`errors`, `src`) | |
| about to say done / fixed / works | `pythia-pg-verify` — evidence first | |
| setup, connection failures, the hooks not running | `pythia-pg doctor`, then `pythia-pg check` | |

Priority when several apply: **process before construction** — impact
before writing, apply's preview before any write, verify before "done".
Announce the skill you opened ("Using pythia-pg-impact — ...") so the
developer sees which page you are on.

## A request with open decisions

A change that leaves real decisions open — data kept or deleted, a column's
type, who may call a function, a security or audit trade-off — becomes
questions with options and a recommendation, asked **before** any code is
written. A new decision found mid-build stops the build.

## Red flags

| Thought | Reality |
|---------|---------|
| "This task is simple" | Simple tasks hide decisions; ask the open ones first. |
| "I'll just run it in psql" | psql has no snapshot, no rehearsal, no journal. The guard denies it. |
| "I remember the schema" | The live catalog is the truth; a dump drifts. `pythia-pg ls`. |
| "I remember what that skill says" | Open the current page. |

## Session state

The session-start brief ends with `STATE` lines: the connections (the
default is starred) and the write policy per group. Read them before
deciding whether a write is even allowed — `data_dml`, `structural` and
`grants` are `deny` until the developer says otherwise.

No STATE line this session means the hooks are not running and the guard
is off: say so to the developer before any write and ask them to run
`pythia-pg doctor`. Every rule still binds.
