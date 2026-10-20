-- Purpose: the first rows an UPDATE or DELETE will touch, for the person
--          approving it to read (one beyond the sample, so a cut is announced)
-- Binds:   none — filled and run like row-set-count.sql
-- Returns: every column of the target
select *
  from /*TARGET*/
 /*WHERE*/
 limit 11
