-- Purpose: whether the plpgsql_check extension is installed in this
--          database — without it, PostgreSQL checks a PL/pgSQL body's syntax
--          at CREATE time and nothing else
-- Binds:   none
-- Returns: INSTALLED (one row, true or false)
select exists (select 1 from pg_extension where extname = 'plpgsql_check')
         as installed
