-- Purpose: the source of every function, procedure or view holding a name,
--          as PostgreSQL itself prints it back — one unit per overload
-- Binds:   %(s)s schema, %(n)s object name (already folded)
-- Returns: UNIT, DEFINITION
select unit, definition
  from (select p.proname || '(' || pg_get_function_identity_arguments(p.oid)
               || ')' as unit,
               pg_get_functiondef(p.oid) as definition,
               1 as k
          from pg_proc p
          join pg_namespace n on n.oid = p.pronamespace
         where n.nspname = %(s)s
           and p.proname = %(n)s
           and p.prokind in ('f', 'p', 'w')
        union all
        select c.relname,
               case c.relkind
                 when 'v' then 'CREATE OR REPLACE VIEW '
                 else 'CREATE MATERIALIZED VIEW ' end
               || quote_ident(n.nspname) || '.' || quote_ident(c.relname)
               || E' AS\n' || pg_get_viewdef(c.oid, true),
               2
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = %(s)s
           and c.relname = %(n)s
           and c.relkind in ('v', 'm')) s
 order by k, unit
