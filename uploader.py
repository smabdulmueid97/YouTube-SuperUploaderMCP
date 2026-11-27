"""Reusable YouTube upload engine for Nevo's 9 channels.

One engine, no per-channel scripts. Every upload goes through this
module, which picks the right OAuth token by channel slug.

Design notes (all verified 2026-11-27):
  - One OAuth token per channel (videos.insert has no channelId
    parameter; the token decides the destination). Tokens live in
    tokens/<slug>.json (mode 600) and are never copied elsewhere,
    never printed, never put in logs.
  - Access tokens auto-refresh from the stored refresh token; the
    refreshed credentials are written back to the same token file.
  - Uploads use the resumable-upload protocol over `requests`
    (proxy-aware). google-api-python-client / httplib2 is NOT used:
    it fails in this environment with SSL WRONG_VERSION_NUMBER.
  - Shorts and long-form use the same videos.insert call. YouTube
    treats a square or vertical video of 3 minutes or less as a
    Short (rule since 15 Oct 2024); this engine detects that with
    ffprobe and records it in the log. Note: a Short over 1 minute
    with an active Content ID claim can be blocked globally.
  - Scheduled publishing: privacyStatus=private + publishAt (UTC).
    The user gives the time in Asia/Dhaka; it is converted here.
  - Duplicate prevention: SHA-256 of the video file is recorded in
    uploads/registry.json. A file already uploaded (or scheduled)
    for that channel is refused unless --force is passed.
  - Safe retry: chunk uploads retry on 5xx / connection errors with
    exponential backoff, and resume from the server-reported offset
    after an interruption. A retry never creates a second video.
  - Dry-run mode validates everything and prints the exact request
    that WOULD be sent, but never calls videos.insert or
    thumbnails.set.

API restrictions (verified 2026-11-27 against Google's official docs):
  - videos.insert costs 1 unit in its own Video Uploads quota
    bucket: 100 calls/day per project by default. (Dec 4, 2025 the
    cost fell from ~1,600 units to ~100; Jun 1, 2026 uploads moved
    into their own bucket. The old "6 uploads/day" figure is wrong.)
    Source: developers.google.com/youtube/v3/docs/videos/insert
    ("Quota impact: 100 calls per day... 1 unit in the Video Uploads
    quota bucket") and the Quota Calculator. 9 uploads/day fits.
  - Privacy: the same page says an upload with no privacyStatus
    defaults to public, and videos from unverified API projects are
    NOT restricted to private anymore. This engine therefore ALWAYS
    sends an explicit privacyStatus (default private) - never rely
    on the API default.
  - While the app is in Testing, refresh tokens expire after 7 days.

SAFE TEST MODE: real uploads are blocked while a file named
SAFE_MODE exists next to this script. Dry-runs always work. Delete
that file ONLY after the user approves real uploads.

Usage (via upload.py):
    python3 upload.py --channel nemonit --video video.mp4 \\
        --title "Title" --description "Desc" --tags a,b,c \\
        --thumbnail thumb.jpg --publish-at "2026-11-28 18:00" --dry-run
"""
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
TOKENS_DIR = HERE / "tokens"
CHANNELS_FILE = HERE / "channels.json"
REGISTRY_FILE = HERE / "uploads" / "registry.json"
LOGS_DIR = HERE / "logs"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
TIMEZONE = ZoneInfo("Asia/Dhaka")
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB resumable chunks
MAX_RETRIES = 5
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API_URL = "https://www.googleapis.com/youtube/v3"
SAFE_MODE_FILE = HERE / "SAFE_MODE"
# videos.insert: 1 unit per call in its own Video Uploads bucket,
# 100 calls/day per project by default (official docs, Nov 2026).
DAILY_INSERT_LIMIT = 100
DAILY_INSERT_WARN_AT = 90


class UploadError(Exception):
    """A failure that should be reported, not retried blindly."""


def load_channels():
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        return {c["slug"]: c for c in json.load(f)["channels"]}


def get_channel(slug):
    channels = load_channels()
    ch = channels.get(slug)
    if ch is None:
        raise UploadError(f"unknown channel slug: {slug} (see channels.json)")
    if not ch.get("channel_id"):
        raise UploadError(f"channel {slug} has no verified channel_id in channels.json")
    return ch


def log_event(slug, event, **fields):
    """Append one JSON line to the channel's own log file.

    Also mirrors the event into Supabase (yt_upload_logs) when the
    mirror is available. The mirror is best-effort: it never raises,
    and the local file is always written first.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    with open(LOGS_DIR / f"{slug}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        import supabase_backend
        supabase_backend.mirror_log(slug, event, record)
    except Exception:  # noqa: BLE001 - the Supabase mirror must never break logging
        pass
    return record


def load_credentials(slug):
    """Load a channel's token, refreshing the access token if needed.

    The refreshed credentials are saved back to the SAME token file
    (mode 600). Nothing is copied anywhere else.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = TOKENS_DIR / f"{slug}.json"
    if not token_path.exists():
        raise UploadError(f"no token for {slug} - run auth_channel.py --channel {slug} first")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            os.chmod(token_path, 0o600)
            log_event(slug, "token_refreshed")
        else:
            raise UploadError(f"token for {slug} is invalid and cannot refresh - re-run OAuth for this channel")
    return creds


def verify_destination(slug, creds):
    """Read-only safety check: the token must belong to the expected channel.

    Returns the verified channel id. Raises if it does not match
    channels.json, so an upload can never go to the wrong channel.
    """
    import requests

    expected = get_channel(slug)
    resp = requests.get(
        f"{API_URL}/channels",
        params={"part": "id", "mine": "true"},
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if len(items) != 1:
        raise UploadError(f"channels.list returned {len(items)} channels for {slug}, expected 1")
    actual_id = items[0]["id"]
    if actual_id != expected["channel_id"]:
        raise UploadError(
            f"token for {slug} belongs to channel {actual_id}, "
            f"expected {expected['channel_id']} ({expected['name']}) - refusing to upload"
        )
    return actual_id


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_video(path):
    """Duration / size via ffprobe. Returns dict; empty values if ffprobe fails."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        )
        data = json.loads(out.stdout)
        video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        return {
            "duration_s": float(data.get("format", {}).get("duration", 0) or 0),
            "width": int(video.get("width", 0) or 0),
            "height": int(video.get("height", 0) or 0),
        }
    except Exception:  # noqa: BLE001 - probe is best-effort; upload still works
        return {"duration_s": 0, "width": 0, "height": 0}


def is_short(probe, force_shorts=None):
    """A Short is a square or vertical video of 3 minutes or less.

    YouTube's rule since 15 Oct 2024 (Help: "Understand three-minute
    YouTube Shorts"): square or vertical aspect ratio, up to 3 min.
    """
    if force_shorts is not None:
        return force_shorts
    d, w, h = probe["duration_s"], probe["width"], probe["height"]
    if d and w and h:
        return d <= 180 and h >= w
    return False


def parse_publish_at(text):
    """'YYYY-MM-DD HH:MM' in Asia/Dhaka -> UTC RFC 3339 string."""
    if not text:
        return None
    try:
        local = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=TIMEZONE)
    except ValueError as exc:
        raise UploadError(f"publish-at must be 'YYYY-MM-DD HH:MM' (Asia/Dhaka), got {text!r}: {exc}")
    if local <= datetime.now(TIMEZONE):
        raise UploadError(f"publish-at {text} is in the past (Asia/Dhaka time)")
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_metadata(title, description, tags):
    if not title or len(title) > 100:
        raise UploadError("title is required and must be 100 characters or less")
    if description and len(description) > 5000:
        raise UploadError("description must be 5000 characters or less")
    if len(tags) > 30:
        raise UploadError("at most 30 tags allowed")
    if sum(len(t) for t in tags) > 500:
        raise UploadError("tags must total 500 characters or less")
    return True


def load_registry():
    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"uploads": []}


def save_registry(registry):
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def find_duplicate(slug, file_hash):
    for rec in load_registry()["uploads"]:
        if rec["slug"] == slug and rec["file_hash"] == file_hash and rec["status"] in ("uploaded", "scheduled"):
            return rec
    return None


def inserts_today():
    """How many videos.insert calls succeeded today (UTC) - quota guard."""
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(
        1 for rec in load_registry()["uploads"]
        if rec.get("uploaded_at", "")[:10] == today and rec["status"] in ("uploaded", "scheduled")
    )


def _request_with_retry(method, url, **kwargs):
    """One HTTP call with exponential backoff on 5xx / connection errors."""
    import requests

    delay = 1
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=120, **kwargs)
            if resp.status_code < 500:
                return resp
            last_exc = UploadError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        except requests.RequestException as exc:
            last_exc = exc
        if attempt < MAX_RETRIES:
            time.sleep(delay)
            delay *= 2
    raise UploadError(f"request failed after {MAX_RETRIES} attempts: {last_exc}")


def _query_upload_offset(session_url, total_bytes):
    """Ask the server how many bytes it already has (resume support)."""
    import requests

    resp = requests.put(
        session_url,
        headers={"Content-Length": "0", "Content-Range": f"bytes */{total_bytes}"},
        timeout=60,
    )
    if resp.status_code == 308:
        rng = resp.headers.get("Range", "")
        if rng.startswith("bytes=0-"):
            return int(rng.split("-")[1]) + 1
        return 0
    if resp.status_code in (200, 201):
        return total_bytes  # already complete
    raise UploadError(f"resume query failed: HTTP {resp.status_code}: {resp.text[:300]}")


def _resumable_upload(creds, metadata, video_path, slug):
    """videos.insert via the resumable upload protocol. Returns video id."""
    import requests

    total = video_path.stat().st_size
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/*",
        "X-Upload-Content-Length": str(total),
    }
    resp = _request_with_retry(
        "POST", UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers=headers, json=metadata,
    )
    if resp.status_code != 200:
        raise UploadError(f"videos.insert start failed: HTTP {resp.status_code}: {resp.text[:500]}")
    session_url = resp.headers.get("Location")
    if not session_url:
        raise UploadError("videos.insert start returned no upload session URL")
    log_event(slug, "upload_session_started", bytes_total=total)

    offset = 0
    with open(video_path, "rb") as f:
        while offset < total:
            f.seek(offset)
            chunk = f.read(CHUNK_SIZE)
            end = offset + len(chunk) - 1
            put_headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {offset}-{end}/{total}",
            }
            try:
                r = requests.put(session_url, headers=put_headers, data=chunk, timeout=300)
            except requests.RequestException:
                # Connection broke mid-chunk: ask the server what it has.
                offset = _query_upload_offset(session_url, total)
                continue
            if r.status_code == 308:
                rng = r.headers.get("Range", "")
                offset = int(rng.split("-")[1]) + 1 if rng.startswith("bytes=0-") else end + 1
                continue
            if r.status_code in (200, 201):
                video_id = r.json().get("id")
                if not video_id:
                    raise UploadError(f"upload finished but no video id returned: {r.text[:300]}")
                return video_id
            if r.status_code >= 500:
                offset = _query_upload_offset(session_url, total)
                continue
            raise UploadError(f"upload chunk failed: HTTP {r.status_code}: {r.text[:500]}")
    raise UploadError("upload loop ended without a video id")


def set_thumbnail(creds, video_id, thumb_path, slug):
    """thumbnails.set - custom thumbnail for an uploaded video."""
    thumb = Path(thumb_path)
    if not thumb.exists():
        raise UploadError(f"thumbnail not found: {thumb}")
    if thumb.stat().st_size > 2 * 1024 * 1024:
        raise UploadError("thumbnail must be under 2 MB")
    with open(thumb, "rb") as f:
        files = {"media": (thumb.name, f, "image/jpeg")}
        resp = _request_with_retry(
            "POST", f"{API_URL}/thumbnails/set",
            params={"videoId": video_id},
            headers={"Authorization": f"Bearer {creds.token}"},
            files=files,
        )
    if resp.status_code != 200:
        raise UploadError(f"thumbnails.set failed: HTTP {resp.status_code}: {resp.text[:500]}")
    log_event(slug, "thumbnail_set", video_id=video_id)
    return True


def upload_video(slug, video_path, title, description="", tags=None, thumbnail=None,
                 publish_at=None, privacy="private", force_shorts=None, force=False,
                 dry_run=False):
    """Upload one video to one channel. Returns a result dict.

    dry_run=True validates everything and prints the exact request
    that would be sent, but makes NO videos.insert / thumbnails.set
    call and writes no registry entry (only a dry-run log line).
    """
    tags = tags or []
    video_path = Path(video_path)
    channel = get_channel(slug)
    validate_metadata(title, description, tags)
    if not video_path.exists():
        raise UploadError(f"video file not found: {video_path}")
    publish_at_utc = parse_publish_at(publish_at)
    probe = probe_video(video_path)
    short = is_short(probe, force_shorts)
    file_hash = sha256_file(video_path)
    file_size = video_path.stat().st_size

    duplicate = find_duplicate(slug, file_hash)
    if duplicate and not force:
        raise UploadError(
            f"duplicate: this file was already uploaded to {channel['name']} "
            f"as video {duplicate['video_id']} ({duplicate['status']}) - use --force to re-upload"
        )

    # Load + refresh the token, then prove it belongs to this channel.
    creds = load_credentials(slug)
    verify_destination(slug, creds)

    status = {"privacyStatus": privacy}
    if publish_at_utc:
        status["privacyStatus"] = "private"  # scheduled videos must start private
        status["publishAt"] = publish_at_utc
    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",  # People & Blogs (safe default; change per video if needed)
        },
        "status": status,
    }
    plan = {
        "channel": channel["name"],
        "channel_id": channel["channel_id"],
        "handle": channel["handle"],
        "video_file": str(video_path),
        "file_size_bytes": file_size,
        "file_sha256": file_hash,
        "duration_s": probe["duration_s"],
        "resolution": f"{probe['width']}x{probe['height']}" if probe["width"] else "unknown",
        "is_short": short,
        "title": title,
        "description_chars": len(description),
        "tags": tags,
        "thumbnail": str(thumbnail) if thumbnail else None,
        "privacy_status": status["privacyStatus"],
        "publish_at_dhaka": publish_at,
        "publish_at_utc": publish_at_utc,
        "metadata_sent_to_youtube": metadata,
    }
    if dry_run:
        log_event(slug, "dry_run", **{k: v for k, v in plan.items() if k != "metadata_sent_to_youtube"},
                  metadata=metadata)
        return {"dry_run": True, "plan": plan}

    if SAFE_MODE_FILE.exists():
        raise UploadError(
            "SAFE TEST MODE is on (SAFE_MODE file present) - real uploads are blocked. "
            "Dry-runs still work. Delete the SAFE_MODE file only after the user approves real uploads."
        )

    today = inserts_today()
    if today >= DAILY_INSERT_LIMIT:
        raise UploadError(
            f"{today} uploads already today - the Video Uploads bucket allows 100/day per project"
        )
    if today >= DAILY_INSERT_WARN_AT:
        log_event(slug, "quota_warning",
                  detail=f"{today} uploads already today; Video Uploads bucket allows 100/day")
    log_event(slug, "upload_started", video_file=str(video_path), file_sha256=file_hash,
              title=title, is_short=short)
    try:
        video_id = _resumable_upload(creds, metadata, video_path, slug)
    except Exception as exc:  # noqa: BLE001 - log the failure, then re-raise
        log_event(slug, "upload_failed", video_file=str(video_path), error=str(exc))
        raise
    log_event(slug, "upload_succeeded", video_id=video_id, title=title, is_short=short)
    if thumbnail:
        set_thumbnail(creds, video_id, thumbnail, slug)

    registry = load_registry()
    new_record = {
        "slug": slug,
        "channel": channel["name"],
        "channel_id": channel["channel_id"],
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "file_name": video_path.name,
        "file_hash": file_hash,
        "title": title,
        "is_short": short,
        "privacy_status": status["privacyStatus"],
        "publish_at_utc": publish_at_utc,
        "status": "scheduled" if publish_at_utc else "uploaded",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "thumbnail_set": bool(thumbnail),
    }
    registry["uploads"].append(new_record)
    save_registry(registry)
    try:
        import supabase_backend
        supabase_backend.mirror_upload(new_record)
    except Exception:  # noqa: BLE001 - the Supabase mirror must never break an upload
        pass
    return {"dry_run": False, "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}", "plan": plan}
