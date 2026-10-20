-- Purpose: the comment on a table, or on one of its columns, as it stands —
--          the snapshot a COMMENT statement is undone with
-- Binds:   %(s)s schema, %(t)s table, %(c)s column, or NULL for the table
-- Returns: COMMENT (one row, NULL when there is none; no row when the table
--          does not exist)
select case when %(c)s::text is null
            then obj_description(c.oid, 'pg_class')
            else (select col_description(c.oid, a.attnum)
                    from pg_attribute a
                   where a.attrelid = c.oid
                     and a.attname = %(c)s
                     and not a.attisdropped)
       end as comment
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = %(s)s
   and c.relname = %(t)s
