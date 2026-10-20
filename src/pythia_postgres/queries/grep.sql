-- Purpose: every function, procedure or view in a schema whose source holds
--          a text, any case, with that source as PostgreSQL prints it back
--          (the engine picks out the lines, numbered as `src` numbers them)
-- Binds:   %(s)s schema, %(t)s the text
-- Returns: UNIT, TYPE, DEFINITION
select unit, type, definition
  from (select p.proname || '(' || pg_get_function_identity_arguments(p.oid)
               || ')' as unit,
               case p.prokind when 'p' then 'PROCEDURE' else 'FUNCTION' end
                 as type,
               pg_get_functiondef(p.oid) as definition
          from pg_proc p
          join pg_namespace n on n.oid = p.pronamespace
         where n.nspname = %(s)s
           and p.prokind in ('f', 'p', 'w')
        union all
        select c.relname,
               case c.relkind when 'v' then 'VIEW' else 'MATERIALIZED VIEW' end,
               -- the same text source.sql prints, so line numbers agree
               case c.relkind
                 when 'v' then 'CREATE OR REPLACE VIEW '
                 else 'CREATE MATERIALIZED VIEW ' end
               || quote_ident(n.nspname) || '.' || quote_ident(c.relname)
               || E' AS\n' || pg_get_viewdef(c.oid, true)
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = %(s)s
           and c.relkind in ('v', 'm')) g
 where strpos(lower(definition), lower(%(t)s)) > 0
 order by type, unit
