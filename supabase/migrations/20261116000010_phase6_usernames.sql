-- Phase 6A: people sign in with a username or their work email. Clerk is the source of
-- truth for the username; this copy is for the admin console's Users list.

alter table users add column if not exists username text;

create unique index if not exists users_username_live_idx on users (lower(username))
    where status <> 'deleted' and username is not null;
