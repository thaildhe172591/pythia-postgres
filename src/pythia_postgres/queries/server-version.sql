-- Purpose: what `check` reports as the server — its version, and the
--          database this session is connected to
-- Binds:   none
-- Returns: VERSION, DATABASE (one row)
select current_setting('server_version') as version,
       current_database()                as database
