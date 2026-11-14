-- The answer cache records a "cache" step (reuse answer) in each eligible run.
alter table run_steps drop constraint if exists run_steps_kind_check;
alter table run_steps add constraint run_steps_kind_check
    check (kind in ('guard', 'llm', 'tool', 'retrieval', 'check', 'cache'));
