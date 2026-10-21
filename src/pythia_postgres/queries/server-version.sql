-- Purpose: what `check` reports as the server — its version, the
--          database this session is connected to, and the version as a
--          number, held against pythia-pg's floor
-- Binds:   none
-- Returns: VERSION, DATABASE, VERSION_NUM (one row)
select current_setting('server_version')          as version,
       current_database()                          as database,
       current_setting('server_version_num')::int  as version_num
