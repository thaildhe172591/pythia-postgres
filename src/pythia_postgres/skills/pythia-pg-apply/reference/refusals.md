# Refusals and the way forward

`pythia-pg apply` refuses what it cannot rehearse, verify or undo honestly.
Each refusal exits 1 and writes nothing. Relay the reason, then offer the
way forward below — never run the statement another way.

| Refused | Why | Way forward |
|---|---|---|
| Several statements in one file | each is previewed, approved and journaled on its own | one file per statement, applied in order |
| `DO $$ ... $$` | an anonymous block can run anything; no policy group fits | put the logic in a function and apply that |
| `CALL proc(...)` | runs a body that can do anything | apply the statements it would run, or the developer runs it by hand |
| `WITH ... INSERT/UPDATE/DELETE` | hides its writes inside a query | a plain INSERT, UPDATE or DELETE |
| `SELECT`, `EXPLAIN`, `SHOW` | apply takes writes; a SELECT can call a function that writes | reads go through `ls`, `src`, `cols`, `grep` |
| `COPY` | reads or writes files outside the database | the developer runs it by hand |
| `CREATE INDEX CONCURRENTLY`, `VACUUM`, `ALTER SYSTEM`, `CREATE DATABASE` | cannot run inside a transaction: no rehearsal, no rollback | the developer runs it by hand, with a DBA watching |
| `CREATE TEMP ...` | dies with the connection, nothing left to verify | not needed through apply |
| `SET ROLE`, `SET SESSION AUTHORIZATION` | changes who verifies the write | connect as the right account |
| `BEGIN`, `COMMIT`, `SAVEPOINT`, `LOCK` | pythia-pg owns the transaction | drop the transaction control |
| psql meta-commands (`\i`, `\set`, `\gexec`) | pythia-pg runs SQL, not psql scripts | plain SQL in the file |
| a file that ends inside a quote or `$$` body | cannot be read safely | close the quote |
| a schema other than the connection's | writing across schemas is refused | `--conn` for the connection that owns it |
| a group set to `deny` | the policy | relay it; loosening is the developer's `policy set`, at a console |

When the gate refuses, the developer may still decide to run the statement
by hand. Hand them the file and, for a definition, the restore from
`pythia-pg history <name>` — never run it for them through psql.
