-- Purpose: what the catalog (pg_depend) records one object as depending on
--          — directly, and for a table or view through its rewrite rules,
--          column defaults, constraints and triggers. System schemas are
--          left out.
-- Binds:   %(classid)s the object's catalog (pg_class or pg_proc, as an oid)
--          %(objid)s   the object's oid
-- Returns: SCHEMA, NAME, TYPE, NEXT_CLASSID, NEXT_OBJID
with parts as (
  select %(classid)s::int8::oid as classid, %(objid)s::int8::oid as objid
  union all
  select 'pg_rewrite'::regclass::oid, r.oid
    from pg_rewrite r
   where %(classid)s::int8::oid = 'pg_class'::regclass::oid
     and r.ev_class = %(objid)s::int8::oid
  union all
  select 'pg_attrdef'::regclass::oid, ad.oid
    from pg_attrdef ad
   where %(classid)s::int8::oid = 'pg_class'::regclass::oid
     and ad.adrelid = %(objid)s::int8::oid
  union all
  select 'pg_constraint'::regclass::oid, k.oid
    from pg_constraint k
   where %(classid)s::int8::oid = 'pg_class'::regclass::oid
     and k.conrelid = %(objid)s::int8::oid
  union all
  select 'pg_trigger'::regclass::oid, t.oid
    from pg_trigger t
   where %(classid)s::int8::oid = 'pg_class'::regclass::oid
     and t.tgrelid = %(objid)s::int8::oid
     and not t.tgisinternal
), refs as (
  select distinct d.refclassid, d.refobjid
    from pg_depend d
    join parts p on d.classid = p.classid and d.objid = p.objid
   where d.deptype in ('n', 'a')
)
select n.nspname as schema,
       c.relname as name,
       case c.relkind when 'r' then 'TABLE'
                      when 'p' then 'PARTITIONED TABLE'
                      when 'v' then 'VIEW'
                      when 'm' then 'MATERIALIZED VIEW'
                      when 'S' then 'SEQUENCE'
                      else 'FOREIGN TABLE' end as type,
       'pg_class'::regclass::oid as next_classid,
       c.oid as next_objid
  from refs
  join pg_class c on refs.refclassid = 'pg_class'::regclass::oid
                 and c.oid = refs.refobjid
  join pg_namespace n on n.oid = c.relnamespace
 where c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')
   and c.oid <> %(objid)s::int8::oid
   and n.nspname not in ('pg_catalog', 'information_schema')
union all
select n.nspname,
       p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       case p.prokind when 'p' then 'PROCEDURE' else 'FUNCTION' end,
       'pg_proc'::regclass::oid,
       p.oid
  from refs
  join pg_proc p on refs.refclassid = 'pg_proc'::regclass::oid
                and p.oid = refs.refobjid
  join pg_namespace n on n.oid = p.pronamespace
 where p.oid <> %(objid)s::int8::oid
   and n.nspname not in ('pg_catalog', 'information_schema')
 order by 3, 2
