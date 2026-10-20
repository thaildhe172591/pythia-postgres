-- Purpose: the CREATE SEQUENCE statement for one sequence
-- Binds:   %(objid)s the sequence's oid
-- Returns: STATEMENT
select 'CREATE SEQUENCE ' || quote_ident(n.nspname) || '.' || quote_ident(c.relname)
       || ' AS ' || format_type(s.seqtypid, null)
       || ' INCREMENT BY ' || s.seqincrement
       || ' MINVALUE ' || s.seqmin
       || ' MAXVALUE ' || s.seqmax
       || ' START WITH ' || s.seqstart
       || ' CACHE ' || s.seqcache
       || case when s.seqcycle then ' CYCLE' else ' NO CYCLE' end || ';'
         as statement
  from pg_sequence s
  join pg_class c on c.oid = s.seqrelid
  join pg_namespace n on n.oid = c.relnamespace
 where s.seqrelid = %(objid)s::int8::oid
