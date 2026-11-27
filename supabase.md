# YouTube uploader — Supabase backend (optional)

The local files are the source of truth (`uploads/registry.json`,
`logs/<slug>.jsonl`). The Supabase mirror is an optional second copy of
the same data, useful for dashboards and history. The mirror is
best-effort and can never break an upload: if one mirror call fails,
mirroring disables itself for the rest of that process.

## Tables (all in `public`)

Create these three tables in your own Supabase project (any project;
use the `yt_` prefix to avoid collisions with your other tables):

- `yt_channels` — your channels. Columns: `slug` (PK), `name`,
  `handle`, `channel_id` (UNIQUE), `subscribers`, `token_status`
  (default 'ok'), `verified_at`. Load one row per channel from
  `channels.json`.
- `yt_uploads` — upload registry, mirrors `uploads/registry.json`.
  Columns: `id` uuid PK, `file_sha256`, `channel_slug` FK → yt_channels,
  `filename`, `title`, `youtube_video_id`, `status` (default 'uploaded'),
  `privacy`, `publish_at`, `is_shorts`, `duration_seconds`, `created_at`.
  UNIQUE (`file_sha256`, `channel_slug`) — same duplicate rule as the
  local registry.
- `yt_upload_logs` — per-channel event logs, mirrors `logs/<slug>.jsonl`.
  Columns: `id` bigint identity PK, `channel_slug` FK → yt_channels,
  `event`, `detail` jsonb, `created_at`.

## Wiring the engine

`supabase_backend.py` mirrors local state into Supabase. It runs your
Supabase client as a subprocess — no Supabase key is stored in the
uploader or in any file; the connection that owns the credential does
the write. Point it at your own Supabase project/connection before
enabling the mirror.

`uploader.py` hooks: `log_event()` also mirrors to `yt_upload_logs`;
after a real upload saves its registry record, `mirror_upload()`
upserts it into `yt_uploads` (ON CONFLICT updates — idempotent).
Dry-runs mirror only the log event, never a registry row.

Verify with: `python3 supabase_backend.py check` (prints row counts),
then run one dry-run upload and confirm a `dry_run` row appears in
`yt_upload_logs` with no registry row created.
