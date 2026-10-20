-- Purpose: the columns of one table or view, for `cols`
-- Binds:   %(objid)s the relation's oid (from resolve.sql)
-- Returns: POSITION, COLUMN_NAME, DATA_TYPE, NULLABLE, COLUMN_DEFAULT, COMMENT
select a.attnum                                   as position,
       a.attname                                  as column_name,
       format_type(a.atttypid, a.atttypmod)       as data_type,
       case when a.attnotnull then 'NO' else 'YES' end as nullable,
       coalesce(pg_get_expr(d.adbin, d.adrelid), '') as column_default,
       coalesce(col_description(a.attrelid, a.attnum), '') as comment
  from pg_attribute a
  left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
 where a.attrelid = %(objid)s::int8::oid
   and a.attnum > 0
   and not a.attisdropped
 order by a.attnum
