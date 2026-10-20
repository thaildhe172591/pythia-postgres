-- Purpose: what the catalog (pg_depend) records as depending on one object:
--          views and materialized views through their rewrite rules,
--          SQL-standard function bodies, triggers, constraints, column
--          defaults and row-level policies. PL/pgSQL bodies are not here —
--          dependents-text.sql looks for those.
-- Binds:   %(classid)s the object's catalog (pg_class or pg_proc, as an oid)
--          %(objid)s   the object's oid
-- Returns: SCHEMA, NAME, TYPE, NEXT_CLASSID, NEXT_OBJID (NULL where the walk
--          stops: nothing depends on a trigger or a constraint)
with d as (
  select distinct classid, objid
    from pg_depend
   where refclassid = %(classid)s::int8::oid
     and refobjid = %(objid)s::int8::oid
     and deptype in ('n', 'a')
)
select n.nspname as schema,
       c.relname as name,
       case c.relkind when 'm' then 'MATERIALIZED VIEW' else 'VIEW' end as type,
       'pg_class'::regclass::oid as next_classid,
       c.oid as next_objid
  from d
  join pg_rewrite r on d.classid = 'pg_rewrite'::regclass::oid and r.oid = d.objid
  join pg_class c on c.oid = r.ev_class
  join pg_namespace n on n.oid = c.relnamespace
 where c.oid <> %(objid)s::int8::oid
union all
select n.nspname,
       p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       case p.prokind when 'p' then 'PROCEDURE' else 'FUNCTION' end,
       'pg_proc'::regclass::oid,
       p.oid
  from d
  join pg_proc p on d.classid = 'pg_proc'::regclass::oid and p.oid = d.objid
  join pg_namespace n on n.oid = p.pronamespace
union all
select n.nspname, t.tgname || ' on ' || c.relname, 'TRIGGER', null, null
  from d
  join pg_trigger t on d.classid = 'pg_trigger'::regclass::oid and t.oid = d.objid
  join pg_class c on c.oid = t.tgrelid
  join pg_namespace n on n.oid = c.relnamespace
 where not t.tgisinternal
union all
select n.nspname, c.relname, 'TABLE (CONSTRAINT ' || k.conname || ')', null, null
  from d
  join pg_constraint k on d.classid = 'pg_constraint'::regclass::oid
                      and k.oid = d.objid
  join pg_class c on c.oid = k.conrelid
  join pg_namespace n on n.oid = c.relnamespace
 where k.conrelid <> %(objid)s::int8::oid
union all
select n.nspname, c.relname, 'TABLE (DEFAULT ' || a.attname || ')', null, null
  from d
  join pg_attrdef ad on d.classid = 'pg_attrdef'::regclass::oid and ad.oid = d.objid
  join pg_class c on c.oid = ad.adrelid
  join pg_attribute a on a.attrelid = ad.adrelid and a.attnum = ad.adnum
  join pg_namespace n on n.oid = c.relnamespace
 where c.oid <> %(objid)s::int8::oid
union all
select n.nspname, pol.polname || ' on ' || c.relname, 'POLICY', null, null
  from d
  join pg_policy pol on d.classid = 'pg_policy'::regclass::oid and pol.oid = d.objid
  join pg_class c on c.oid = pol.polrelid
  join pg_namespace n on n.oid = c.relnamespace
 where c.oid <> %(objid)s::int8::oid
 order by 3, 2
