-- Purpose: what the first line of a table's DDL needs — its qualified name,
--          persistence, partition key, and the parent it is a partition of
-- Binds:   %(objid)s the table's oid
-- Returns: QNAME, UNLOGGED, PARTITION_KEY, PARTITION_OF, PARTITION_BOUND
select quote_ident(n.nspname) || '.' || quote_ident(c.relname) as qname,
       c.relpersistence = 'u' as unlogged,
       case when c.relkind = 'p' then pg_get_partkeydef(c.oid) end as partition_key,
       (select quote_ident(pn.nspname) || '.' || quote_ident(pc.relname)
          from pg_inherits i
          join pg_class pc on pc.oid = i.inhparent
          join pg_namespace pn on pn.oid = pc.relnamespace
         where c.relispartition
           and i.inhrelid = c.oid) as partition_of,
       case when c.relispartition then pg_get_expr(c.relpartbound, c.oid) end
         as partition_bound
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where c.oid = %(objid)s::int8::oid
