-- Purpose: where an unqualified name lands for this session: the first
--          schema on search_path that exists, NULL when none does
-- Binds:   none
-- Returns: CURRENT_SCHEMA (one row)
select current_schema() as current_schema
