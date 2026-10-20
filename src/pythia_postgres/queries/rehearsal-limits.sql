-- Purpose: bound a rehearsal, for this transaction only: a preview must not
--          hold locks or rewrite a large table for long (the confirm run is
--          the same rehearsal, so the write gets the same bounds)
-- Binds:   %(st)s statement_timeout, %(lt)s lock_timeout (e.g. '30s', '5s')
-- Returns: STATEMENT_TIMEOUT, LOCK_TIMEOUT
select set_config('statement_timeout', %(st)s, true) as statement_timeout,
       set_config('lock_timeout', %(lt)s, true) as lock_timeout
