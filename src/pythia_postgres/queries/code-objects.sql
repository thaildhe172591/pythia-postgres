-- Purpose: every function, procedure and view in a schema holding a name,
--          with the statement that recreates it and the signature that drops
--          it — what a write can replace, snapshotted before it runs
-- Binds:   %(s)s schema, %(n)s object name (already folded)
-- Returns: UNIT, KIND, QUALIFIED, DEFINITION
select p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
         as unit,
       case p.prokind when 'p' then 'PROCEDURE' else 'FUNCTION' end as kind,
       quote_ident(n.nspname) || '.' || quote_ident(p.proname) || '('
       || pg_get_function_identity_arguments(p.oid) || ')' as qualified,
       pg_get_functiondef(p.oid) as definition
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = %(s)s
   and p.proname = %(n)s
   and p.prokind in ('f', 'p', 'w')
union all
select c.relname,
       'VIEW',
       quote_ident(n.nspname) || '.' || quote_ident(c.relname),
       'CREATE OR REPLACE VIEW ' || quote_ident(n.nspname) || '.'
       || quote_ident(c.relname) || E' AS\n' || pg_get_viewdef(c.oid, true)
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = %(s)s
   and c.relname = %(n)s
   and c.relkind = 'v'
 order by 1
