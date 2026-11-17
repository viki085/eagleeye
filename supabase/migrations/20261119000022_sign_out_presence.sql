-- Sign-out shows in the admin console at once, instead of after the 5-minute "online" window.
--
-- users.signed_out_at: a company user counts as online only when active since their last
-- sign-out. demo_sessions.ended_at: a demo sign-in session that was signed out; a visit is
-- online only through a session that is still open. last_seen_at keeps its real time, so
-- "last seen" / "last active" in the console are unchanged.

alter table users add column if not exists signed_out_at timestamptz;
alter table demo_sessions add column if not exists ended_at timestamptz;
