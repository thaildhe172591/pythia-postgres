-- Purpose: put the configured schema first on search_path for the rest of
--          this transaction only, so a checker resolves unqualified names as
--          the application whose schema it is would; allowed in a read-only
--          transaction, and gone when it ends. Also says whether this account
--          may use the schema at all: without USAGE, PostgreSQL leaves it off
--          the path silently and every name in it looks missing.
-- Binds:   %(s)s schema
-- Returns: SEARCH_PATH (the path now in force), SCHEMA_USAGE, ACCOUNT
select set_config('search_path',
                  quote_ident(%(s)s) || ', ' || current_setting('search_path'),
                  true) as search_path,
       has_schema_privilege(%(s)s, 'USAGE') as schema_usage,
       current_user as account
