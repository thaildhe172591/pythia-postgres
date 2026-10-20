-- Purpose: the statements that follow a CREATE TABLE: indexes no constraint
--          owns, triggers, and comments on the table and its columns
-- Binds:   %(objid)s the table's oid
-- Returns: STATEMENT
select stmt as statement
  from (select 1 as k, ic.relname as sort_key,
               pg_get_indexdef(i.indexrelid) || ';' as stmt
          from pg_index i
          join pg_class ic on ic.oid = i.indexrelid
         where i.indrelid = %(objid)s::int8::oid
           and not exists (select 1 from pg_constraint k
                            where k.conindid = i.indexrelid
                              and k.contype in ('p', 'u', 'x'))
        union all
        select 2, t.tgname, pg_get_triggerdef(t.oid, true) || ';'
          from pg_trigger t
         where t.tgrelid = %(objid)s::int8::oid
           and not t.tgisinternal
        union all
        select 3, '',
               'COMMENT ON TABLE ' || quote_ident(n.nspname) || '.'
               || quote_ident(c.relname) || ' IS ' || quote_literal(d.description)
               || ';'
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
          join pg_description d on d.objoid = c.oid
                               and d.classoid = 'pg_class'::regclass
                               and d.objsubid = 0
         where c.oid = %(objid)s::int8::oid
        union all
        select 4, lpad(a.attnum::text, 6, '0'),
               'COMMENT ON COLUMN ' || quote_ident(n.nspname) || '.'
               || quote_ident(c.relname) || '.' || quote_ident(a.attname)
               || ' IS ' || quote_literal(d.description) || ';'
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
          join pg_attribute a on a.attrelid = c.oid
          join pg_description d on d.objoid = c.oid
                               and d.classoid = 'pg_class'::regclass
                               and d.objsubid = a.attnum
         where c.oid = %(objid)s::int8::oid
           and a.attnum > 0) x
 order by k, sort_key
