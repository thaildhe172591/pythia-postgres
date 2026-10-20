-- Purpose: every relation and function outside the system schemas, by bare
--          name — what a word in a function body could be referring to
-- Binds:   none
-- Returns: BARE_NAME, SCHEMA, NAME, TYPE, NEXT_CLASSID, NEXT_OBJID
select c.relname as bare_name,
       n.nspname as schema,
       c.relname as name,
       case c.relkind when 'r' then 'TABLE'
                      when 'p' then 'PARTITIONED TABLE'
                      when 'v' then 'VIEW'
                      when 'm' then 'MATERIALIZED VIEW'
                      when 'S' then 'SEQUENCE'
                      else 'FOREIGN TABLE' end as type,
       'pg_class'::regclass::oid as next_classid,
       c.oid as next_objid
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')
   and n.nspname not in ('pg_catalog', 'information_schema')
   and n.nspname not like 'pg\_%%'
union all
select p.proname,
       n.nspname,
       p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       case p.prokind when 'p' then 'PROCEDURE' else 'FUNCTION' end,
       'pg_proc'::regclass::oid,
       p.oid
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
 where p.prokind in ('f', 'p', 'w')
   and n.nspname not in ('pg_catalog', 'information_schema')
   and n.nspname not like 'pg\_%%'
