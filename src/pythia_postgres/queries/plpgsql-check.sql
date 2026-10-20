-- Purpose: what plpgsql_check reports for the PL/pgSQL functions of a schema,
--          or those holding one name. A trigger function is checked against
--          the first table whose trigger uses it; one no trigger uses cannot
--          be checked (plpgsql-unchecked.sql names those).
-- Binds:   %(s)s schema, %(n)s object name or NULL for the whole schema
-- Returns: NAME, TYPE, LINE, POSITION, SEVERITY, MESSAGE
select p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
         as name,
       case p.prokind when 'p' then 'PROCEDURE' else 'FUNCTION' end as type,
       c.lineno as line,
       c.position as position,
       c.level as severity,
       c.message || coalesce(' (' || c.detail || ')', '') as message
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  join pg_language l on l.oid = p.prolang and l.lanname = 'plpgsql'
 cross join lateral plpgsql_check_function_tb(
         p.oid,
         coalesce((select t.tgrelid from pg_trigger t
                    where t.tgfoid = p.oid
                    order by t.oid limit 1), 0)) c
 where n.nspname = %(s)s
   and (%(n)s::text is null or p.proname = %(n)s)
   and p.prorettype <> 'event_trigger'::regtype
   and (p.prorettype <> 'trigger'::regtype
        or exists (select 1 from pg_trigger t where t.tgfoid = p.oid))
 order by 1, 3
