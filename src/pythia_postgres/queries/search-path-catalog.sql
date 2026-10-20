-- Purpose: leave only pg_catalog on search_path for the rest of this
--          transaction, as pg_dump does, so every name the catalog prints
--          back (defaults, indexes, constraints, views) comes out qualified
--          and the DDL runs the same from any session
-- Binds:   none
-- Returns: SEARCH_PATH
select set_config('search_path', 'pg_catalog', true) as search_path
