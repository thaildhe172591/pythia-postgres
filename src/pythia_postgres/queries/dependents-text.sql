-- Purpose: functions whose source text holds a name as a whole word, any
--          case — the references pg_depend does not record (PL/pgSQL
--          bodies, SQL functions with a string body). A match is a lead, not
--          a proof: a column or a variable can share the name.
-- Binds:   %(pattern)s the name as a whole-word regular expression, escaped
--                      by the engine
--          %(objid)s   the object itself, left out
-- Returns: SCHEMA, NAME, TYPE, NEXT_CLASSID, NEXT_OBJID
select n.nspname as schema,
       p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' as name,
       case p.prokind when 'p' then 'PROCEDURE' else 'FUNCTION' end as type,
       'pg_proc'::regclass::oid as next_classid,
       p.oid as next_objid
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  join pg_language l on l.oid = p.prolang
 where l.lanname in ('plpgsql', 'sql')
   and n.nspname not in ('pg_catalog', 'information_schema')
   and n.nspname not like 'pg\_%%'
   and p.oid <> %(objid)s::int8::oid
   and p.prosrc ~* %(pattern)s
 order by 1, 2
