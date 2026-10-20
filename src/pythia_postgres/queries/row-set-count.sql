-- Purpose: how many rows an UPDATE or DELETE will touch, and a fingerprint of
--          which (their ctids: an update in between gives a row a new one)
-- Binds:   none — the engine puts the statement's own table and predicate
--          where the TARGET and WHERE markers stand, and runs the text with
--          no parameters, so a percent sign in the predicate is read as
--          written
-- Returns: N, FINGERPRINT
select count(*) as n,
       md5(coalesce(string_agg(ctid::text, ',' order by ctid), '')) as fingerprint
  from /*TARGET*/
 /*WHERE*/
