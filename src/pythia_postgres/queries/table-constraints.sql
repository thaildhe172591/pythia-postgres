-- Purpose: a table's primary key, unique, check, exclusion and foreign key
--          constraints as PostgreSQL prints them back (NOT NULL is on the
--          columns, so contype 'n' of PostgreSQL 18 is left out)
-- Binds:   %(objid)s the table's oid
-- Returns: NAME, DEFINITION
select quote_ident(k.conname)            as name,
       pg_get_constraintdef(k.oid, true) as definition
  from pg_constraint k
 where k.conrelid = %(objid)s::int8::oid
   and k.contype in ('p', 'u', 'c', 'x', 'f')
 order by case k.contype when 'p' then 1 when 'u' then 2 when 'c' then 3
                         when 'x' then 4 else 5 end,
          k.conname
