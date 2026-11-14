-- Notebook mode: an analyst-style notebook is an artifact too (manifest JSON in the artifacts
-- bucket, figures as PNG objects next to it; its tables are ordinary 'table' artifacts).
alter table artifacts drop constraint if exists artifacts_type_check;
alter table artifacts add constraint artifacts_type_check
    check (type in ('table', 'chart', 'profile', 'notebook'));
