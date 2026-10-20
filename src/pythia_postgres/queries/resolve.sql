-- Purpose: every object in a schema holding a name — relations, and each
--          overload of a function — as the catalog identifies it, so the
--          dependency walks can start from oids instead of names
-- Binds:   %(s)s schema, %(n)s object name (already folded)
-- Returns: CLASSID, OBJID, TYPE, LABEL, BARE_NAME
select 'pg_class'::regclass::oid as classid,
       c.oid                     as objid,
       case c.relkind when 'r' then 'TABLE'
                      when 'p' then 'PARTITIONED TABLE'
                      when 'v' then 'VIEW'
                      when 'm' then 'MATERIALIZED VIEW'
                      when 'S' then 'SEQUENCE'
                      when 'f' then 'FOREIGN TABLE' end as type,
       c.relname                 as label,
       c.relname                 as bare_name
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = %(s)s
   and c.relname = %(n)s
   and c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')
union all
select 'pg_proc'::regclass::oid,
       p.oid,
       case p.prokind when 'p' then 'PROCEDURE'
                      when 'a' then 'AGGREGATE'
                      when 'w' then 'WINDOW FUNCTION'
                      else 'FUNCTION' end,
       p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       p.proname
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = %(s)s
   and p.proname = %(n)s
 order by 3, 4
