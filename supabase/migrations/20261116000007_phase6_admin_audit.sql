-- Phase 6A: admin console actions (kill switches, clearing stuck runs) are audited in
-- security_events next to guard blocks and output-filter events.

alter table security_events drop constraint security_events_kind_check;
alter table security_events add constraint security_events_kind_check
    check (kind in ('input_blocked', 'output_filtered', 'guard_unavailable', 'admin_action'));
