-- Purpose: objects in a schema whose name matches a LIKE pattern in any case,
--          for `ls`: relations, functions and procedures, triggers, and
--          stand-alone types
-- Binds:   %(s)s schema, %(p)s LIKE pattern, %(n)s row cap
-- Returns: NAME, TYPE, DETAIL (comment, signature, or the trigger's table)
select name, type, detail
  from (select c.relname as name,
               case c.relkind when 'r' then 'TABLE'
                              when 'p' then 'PARTITIONED TABLE'
                              when 'v' then 'VIEW'
                              when 'm' then 'MATERIALIZED VIEW'
                              when 'S' then 'SEQUENCE'
                              when 'f' then 'FOREIGN TABLE' end as type,
               coalesce(obj_description(c.oid, 'pg_class'), '') as detail
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = %(s)s
           and c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')
           and c.relname ilike %(p)s
        union all
        select p.proname,
               case p.prokind when 'p' then 'PROCEDURE'
                              when 'a' then 'AGGREGATE'
                              when 'w' then 'WINDOW FUNCTION'
                              else 'FUNCTION' end,
               '(' || pg_get_function_identity_arguments(p.oid) || ')'
          from pg_proc p
          join pg_namespace n on n.oid = p.pronamespace
         where n.nspname = %(s)s
           and p.proname ilike %(p)s
        union all
        select t.tgname, 'TRIGGER', 'on ' || c.relname
          from pg_trigger t
          join pg_class c on c.oid = t.tgrelid
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = %(s)s
           and not t.tgisinternal
           and t.tgname ilike %(p)s
        union all
        select ty.typname,
               case ty.typtype when 'e' then 'ENUM'
                               when 'd' then 'DOMAIN'
                               when 'r' then 'RANGE'
                               else 'TYPE' end,
               ''
          from pg_type ty
          join pg_namespace n on n.oid = ty.typnamespace
         where n.nspname = %(s)s
           and ty.typname ilike %(p)s
           and (ty.typtype in ('e', 'd', 'r')
                or (ty.typtype = 'c'
                    and exists (select 1 from pg_class rc
                                 where rc.oid = ty.typrelid
                                   and rc.relkind = 'c')))) o
 order by type, name
 limit %(n)s
