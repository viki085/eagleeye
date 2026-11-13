-- Phase 6A: admin-managed accounts (enterprise: no self-signup).
-- Deleting a user revokes sign-in and marks the row 'deleted'; billing (usage_ledger) and
-- audit rows that reference it stay intact. Re-adding the same email reactivates the row.

alter table users drop constraint users_status_check;
alter table users add constraint users_status_check
    check (status in ('active', 'disabled', 'deleted'));

alter table users add column if not exists created_by uuid references users (id) on delete set null;

-- one live account per email (case-insensitive); deleted rows don't block re-adding
create unique index if not exists users_email_live_idx on users (lower(email))
    where status <> 'deleted';
