-- Purpose: the PL/pgSQL functions plpgsql-check.sql cannot check — trigger
--          functions no trigger uses, and event trigger functions — so the
--          gap is named instead of read as clean
-- Binds:   %(s)s schema, %(n)s object name or NULL for the whole schema
-- Returns: NAME
select p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
         as name
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  join pg_language l on l.oid = p.prolang and l.lanname = 'plpgsql'
 where n.nspname = %(s)s
   and (%(n)s::text is null or p.proname = %(n)s)
   and (p.prorettype = 'event_trigger'::regtype
        or (p.prorettype = 'trigger'::regtype
            and not exists (select 1 from pg_trigger t where t.tgfoid = p.oid)))
 order by 1
