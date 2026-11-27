# YouTube uploader — Supabase backend

Set up 2026-11-27 via Composio (connection `supabase_secund-triage`, verified working).

## Project

- Project: **govtexam**
- Ref: `fiuvihmwkcxazfkqenpn`
- Region: ap-northeast-1, Postgres 17, status ACTIVE_HEALTHY
- The project already hosts the govtexam app (16 tables in `public`). YouTube
  tables use the `yt_` prefix to avoid collisions. Nothing in the govtexam
  tables was touched.

## Tables (all in `public`)

- `yt_channels` — the 9 verified channels. Columns: `slug` (PK), `name`,
  `handle`, `channel_id` (UNIQUE), `subscribers`, `token_status` (default
  'ok'), `verified_at`. Loaded 2026-11-27: 9 rows, channel IDs match
  `channels.json`.
- `yt_uploads` — upload registry, replaces `uploads/registry.json`.
  Columns: `id` uuid PK, `file_sha256`, `channel_slug` FK → yt_channels,
  `filename`, `title`, `youtube_video_id`, `status` (default 'uploaded'),
  `privacy`, `publish_at`, `is_shorts`, `duration_seconds`, `created_at`.
  UNIQUE (`file_sha256`, `channel_slug`) — same duplicate rule as the local
  registry.
- `yt_upload_logs` — per-channel event logs, replaces `logs/<slug>.jsonl`.
  Columns: `id` bigint identity PK, `channel_slug` FK → yt_channels,
  `event`, `detail` jsonb, `created_at`.

Validation 2026-11-27: channels=9, uploads=0, logs=0.

## Wiring the engine (done 2026-11-27)

- `supabase_backend.py` mirrors local state into Supabase through the
  Composio MCP client (the verified Supabase connection) — no Supabase
  key is stored in the uploader or in any file. Each mirror call runs
  the Composio client as a subprocess (a few seconds per call).
- `uploader.py` hooks: `log_event()` also mirrors to `yt_upload_logs`;
  after a real upload saves its registry record, `mirror_upload()`
  upserts it into `yt_uploads` (ON CONFLICT updates — idempotent).
- Rules: local files stay the source of truth; the mirror is
  best-effort and can never raise into the engine; after one failed
  mirror in a process, mirroring disables itself for that process.
  Dry-runs mirror only the log event, never a registry row.
- Verified 2026-11-27: `python3 supabase_backend.py check` →
  channels=9, logs=0, uploads=0; then a dry-run Shorts upload to
  Nemonit wrote its local log line AND a `dry_run` row in
  `yt_upload_logs` (logs=1, uploads=0, no registry file created).
  No Supabase key is stored in the uploader: the mirror runs through
  the Composio connection, which owns the credential.

## Cloudflare status (2026-11-27)

The Composio Cloudflare connection (`cloudflare_albian-wail`) shows ACTIVE in
Composio, but every real API call fails: Cloudflare returns 400
"Invalid format for X-Auth-Key header" (error 6103). The stored credential is
wrong or the wrong type. Website deploy is blocked until the user reconnects
Cloudflare in Composio with a valid credential.
