-- Purpose: whether this session can do far more than changing one schema
--          needs: a superuser, a role that creates roles, or the schema's
--          owner
-- Binds:   %(s)s schema
-- Returns: SUPERUSER, CREATEROLE, OWNS_SCHEMA, ACCOUNT
select r.rolsuper as superuser,
       r.rolcreaterole as createrole,
       coalesce((select ns.nspowner = r.oid
                   from pg_namespace ns
                  where ns.nspname = %(s)s), false) as owns_schema,
       r.rolname as account
  from pg_roles r
 where r.rolname = current_user
