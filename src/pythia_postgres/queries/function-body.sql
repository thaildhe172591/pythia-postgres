-- Purpose: a function's language and its source as stored — the text the
--          engine reads for references pg_depend does not record
-- Binds:   %(objid)s the function's oid
-- Returns: LANGUAGE, BODY
select l.lanname as language, p.prosrc as body
  from pg_proc p
  join pg_language l on l.oid = p.prolang
 where p.oid = %(objid)s::int8::oid
