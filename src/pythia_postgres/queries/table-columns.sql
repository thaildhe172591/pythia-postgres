-- Purpose: column definitions as a CREATE TABLE writes them, defaults,
--          identity and generated expressions included
-- Binds:   %(objid)s the table's oid
-- Returns: NAME, DATA_TYPE, NOT_NULL, DEFAULT_EXPR, IDENTITY, GENERATED
select quote_ident(a.attname)                     as name,
       format_type(a.atttypid, a.atttypmod)       as data_type,
       a.attnotnull                               as not_null,
       pg_get_expr(d.adbin, d.adrelid)            as default_expr,
       a.attidentity                              as identity,
       a.attgenerated                             as generated
  from pg_attribute a
  left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
 where a.attrelid = %(objid)s::int8::oid
   and a.attnum > 0
   and not a.attisdropped
 order by a.attnum
