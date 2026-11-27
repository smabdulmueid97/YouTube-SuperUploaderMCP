# Cloudflare + Supabase for the YouTube uploader — plan

Prepared 2026-11-27 15:54 Asia/Dhaka, after Nevo asked to
"use cloudflare and super base to setup the yputube thing".
No video uploaded, no tokens moved, SAFE_MODE still on.
Nothing here publishes anything or starts automation.

## Verified starting point

- 9/9 channel OAuth tokens verified 2026-11-27 (channels.list mine=true),
  in `~/workspace/youtube-uploader/tokens/` (9 files, one per channel).
  Channel list in `channels.json` is the source of truth.
- Uploader engine built and dry-run tested; SAFE_MODE file present,
  so real uploads are blocked until Nevo approves.
- Website files ready, separate pages, no invented URLs:
  `website/index.html` (home) + `website/privacy.html` + `DEPLOY.md`.
  Domain is still the placeholder YOUR-DOMAIN-HERE.
- Google OAuth app still in Testing: tokens expire after 7 days.
  Tokens were verified 2026-11-27 ~15:15-15:35 Dhaka, so they expire
  around 2026-12-04 unless the app is Published before then.
  Publishing needs real home-page + privacy-policy URLs first.
- Cloudflare in Muse: checked 2026-11-27 15:54 Dhaka via
  `/opt/hatch/bin/cloudflare status` -> `{"ok":true,"status":"not_connected"}`.
  No Cloudflare account is connected in Muse yet. Connecting is an
  authorize-url step (no password/token in chat); the user may already
  have a Cloudflare account outside Muse — that is still unknown.
- Supabase in Muse: no Supabase connector exists (connector search,
  2026-11-27). Route is a custom connector with an API key via Muse's
  secure credentials store (see `custom-connector-setup` skill), or
  possibly via the Composio connector connected 2026-11-27 (12 tools,
  incl. COMPOSIO_SEARCH_TOOLS) — Composio Supabase coverage not yet checked.
- Main agent asked Nevo at 15:54 Dhaka which scope he means and whether
  he already has Cloudflare / Supabase accounts. No answer yet in the
  supplied conversation. Do not re-ask until he replies; this plan is
  the groundwork for whichever scope he picks.

## Recommended scope (fastest unblock)

**Website on Cloudflare + uploader data in Supabase — not moving the
whole uploader to the cloud yet.** Reasons:

1. Cloudflare Pages can host the two static pages for free and gives a
   real public URL (`https://<project>.pages.dev`) — no owned domain
   needed to satisfy Google's home-page + privacy-policy fields, and
   Nevo's own domain can be attached later in Cloudflare if he has one.
   This alone unblocks Publishing the OAuth app before the ~Dec 4
   token expiry.
2. Supabase (Postgres) can hold the upload queue, the upload registry
   (mirror of `uploads/registry.json`) and per-channel logs (mirror of
   `logs/<slug>.jsonl`), so that state survives outside this machine
   and the dashboard can read it from anywhere.
3. Do NOT move the tokens or the upload engine to the cloud in this
   step. The privacy policy just written says tokens are stored only
   on the owner's own machine; moving 9 refresh tokens + the OAuth
   client secret into Cloudflare Workers / Supabase would be a new
   security decision, and Workers cannot run the Python resumable
   uploader as-is. Keep tokens local; Supabase stores metadata only,
   never tokens, client secrets, or video files.

If Nevo instead picks "just the website", step 1 alone is the whole job.
If he picks "move the whole uploader to the cloud", that needs a
separate design pass (token storage in Cloudflare Secrets / Supabase
Vault, Workers rewrite, video storage) — do not start it on this plan.

## Supabase schema draft (metadata only — no tokens)

```sql
-- channels: mirror of channels.json (9 rows)
create table channels (
  slug text primary key,
  channel_id text unique not null,
  name text not null,
  handle text,
  subscribers int,
  verified_at timestamptz
);

-- upload_queue: one row per planned upload
create table upload_queue (
  id uuid primary key default gen_random_uuid(),
  channel_slug text references channels(slug),
  video_file text not null,
  file_sha256 text not null,
  title text not null,
  description text,
  tags text[],
  thumbnail_path text,
  privacy_status text not null default 'private',
  publish_at timestamptz,          -- Asia/Dhaka input, stored as UTC
  is_short boolean,
  status text not null default 'queued',  -- queued|uploading|done|failed
  youtube_video_id text,
  error text,
  created_at timestamptz default now(),
  unique (channel_slug, file_sha256)  -- duplicate prevention, mirrors registry.json
);

-- uploads: completed / attempted uploads = registry + logs mirror
create table uploads (
  id uuid primary key default gen_random_uuid(),
  channel_slug text references channels(slug),
  file_sha256 text not null,
  title text,
  youtube_video_id text,
  privacy_status text,
  publish_at timestamptz,
  event text not null,             -- dry_run|started|succeeded|failed|thumbnail_set
  created_at timestamptz default now()
);
```

Enable Row Level Security on all three tables; use the Supabase
service-role key only from the trusted uploader, anon key read-only
for the dashboard if one is ever published.

## Steps in order (for delivery, once Nevo answers scope + accounts)

1. Cloudflare: run `cloudflare authorize-url`, share only the returned
   `connect_url` for Nevo to connect his account. Then create a Pages
   project from `website/index.html` + `website/privacy.html`
   (or `wrangler pages deploy`), note the `*.pages.dev` URL.
2. Supabase: if no project, create one at supabase.com (browser);
   if one exists, connect via secure credentials store with its API
   key (never in chat) and run the schema above.
3. Replace YOUR-DOMAIN-HERE in the two website files with the Pages
   URL only after deployment is confirmed live (open both URLs).
4. Google Cloud Console -> OAuth consent screen -> Branding: enter
   home page `https://<project>.pages.dev/` and privacy policy
   `https://<project>.pages.dev/privacy.html`, then Publish app.
5. Re-run `verify_channels.py` (live token check, 9/9) after
   Publishing, before any test upload. SAFE_MODE stays on until Nevo
   approves a real test video.
6. Only then: point the uploader's logs/registry at Supabase
   (queue + uploads tables) and re-run the dry-run tests.

## Update — scope settled in live chat after this plan was written

- 2026-11-27 09:54:59 UTC / 15:54:59 Dhaka, user: "Website on
  Cloudflare + uploader data in Supabase" — the recommended scope
  above. That question is answered; do not re-ask it.
- Main agent then asked for a Cloudflare connect + whether a Supabase
  project exists. User replied ~09:55:25 UTC: "use composio, got all
  connected".
- Reading of that reply: use the Composio connector (connected
  2026-11-27, 12 tools) instead of the native Cloudflare connector,
  and the user believes Cloudflare + Supabase are already connected
  there. NOT yet verified — no Composio tool search was run in this
  research run. Delivery must verify before claiming it:
  use COMPOSIO_SEARCH_TOOLS for "Cloudflare Pages deploy" and
  "Supabase create table / insert row", and
  COMPOSIO_MANAGE_CONNECTIONS to confirm a Cloudflare connection
  and a Supabase connection actually exist in Composio. If either
  is missing, fall back to the native Cloudflare authorize-url step
  (connector doc `/opt/hatch/connectors/cloudflare/CONNECTOR.md`)
  and the Supabase API-key secure-store route.
- Note the apparent contradiction, resolved: Muse's native Cloudflare
  connector reports `not_connected` (checked this run), while the
  user says the connections exist in Composio. Both can be true —
  Composio holds its own connections. Do not tell the user Cloudflare
  "isn't connected" without the Composio check.

## Still needed from Nevo (already asked 15:54 Dhaka — do not re-ask now)

- Scope: SETTLED — website on Cloudflare + uploader data in Supabase.
- Cloudflare / Supabase via Composio: verify at delivery (see above).
  If Composio lacks either connection, ask for that one only.
- Video topics per channel + test-video choice (still open from
  earlier; not blocking this setup).
