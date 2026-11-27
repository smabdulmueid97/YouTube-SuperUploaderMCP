"""Supabase mirror for the YouTube uploader (metadata only, never tokens).

The uploader's source of truth stays local: `uploads/registry.json` and
`logs/<slug>.jsonl`. This module mirrors those writes into Supabase
(project "govtexam", tables `yt_channels`, `yt_uploads`, `yt_upload_logs`)
so the state survives outside this machine and can be read from anywhere.

How it talks to Supabase: through the Composio MCP client, which already
holds a verified working Supabase connection (supabase_secund-triage).
No Supabase key lives in this file or in the uploader — the Composio
connection owns the credential. Each mirror call runs the client as a
subprocess (a few seconds per call; acceptable for daily uploads).

Safety rules:
  - Every function here is best-effort and NEVER raises into the engine.
    A failed mirror returns False; the local write already happened.
  - After the first failed mirror in a process, mirroring disables
    itself for the rest of that process (circuit breaker) so a broken
    Composio/Supabase link cannot slow every log call.
  - Dry-runs mirror only the log event, never a registry row — same
    rule as the local files (a dry-run writes no registry entry).

Tables (created 2026-11-27, see supabase.md):
  - yt_upload_logs (channel_slug, event, detail jsonb, created_at)
  - yt_uploads (file_sha256, channel_slug, filename, title,
    youtube_video_id, status, privacy, publish_at, is_shorts,
    duration_seconds, created_at) with UNIQUE (file_sha256, channel_slug)
"""

import json
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPOSIO_CLIENT = Path.home() / "workspace" / "custom-connectors" / "custom.composio" / "bin" / "client.py"
PROJECT_REF = "fiuvihmwkcxazfkqenpn"
_SUBPROCESS_TIMEOUT = 30  # seconds per mirror call

_disabled = False  # circuit breaker: set True after the first failed mirror


def enabled():
    """True when mirroring is possible in this process."""
    return not _disabled and COMPOSIO_CLIENT.exists()


def _sql_literal(value):
    """Render a Python value as a Postgres literal. Strings are quoted
    with embedded single quotes doubled; dicts/lists become jsonb."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def _run_tool(tool_slug, arguments):
    """Run one Composio toolkit tool via the MCP client. Returns
    (ok, data_dict_or_error_string). Never raises."""
    global _disabled
    if not enabled():
        return False, "supabase mirror disabled"
    payload = {
        "tools": [{"tool_slug": tool_slug, "arguments": arguments}],
        "thought": "Mirror uploader state to Supabase.",
        "memory": {"supabase": ["Project govtexam, ref fiuvihmwkcxazfkqenpn."]},
        "current_step": "MIRRORING_TO_SUPABASE",
        "sync_response_to_workbench": False,
    }
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(payload, f)
            tmp = f.name
        proc = subprocess.run(
            ["python3", str(COMPOSIO_CLIENT), "call-tool",
             "--name", "COMPOSIO_MULTI_EXECUTE_TOOL",
             "--arguments-file", tmp],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        outer = json.loads(proc.stdout)
        inner = json.loads(outer["content"][0]["text"])
        result = inner["data"]["results"][0]
        response = result["response"]
        if not response.get("successful"):
            return False, str(response.get("error") or response.get("data", {}))[:300]
        return True, response.get("data", {})
    except Exception as exc:  # noqa: BLE001 - mirror must never break the engine
        _disabled = True
        return False, f"{type(exc).__name__}: {exc}"[:300]
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def _run_sql(query, read_only=False):
    """Run one SQL statement via Composio. Returns (ok, data_or_error)."""
    tool = "SUPABASE_RUN_READ_ONLY_QUERY" if read_only else "SUPABASE_BETA_RUN_SQL_QUERY"
    args = {"ref": PROJECT_REF, "query": query}
    if not read_only:
        args["read_only"] = False
    return _run_tool(tool, args)


def mirror_log(slug, event, fields):
    """Mirror one log_event() call into yt_upload_logs. Best-effort."""
    if not enabled():
        return False
    detail = _sql_literal(dict(fields))
    query = (
        "INSERT INTO public.yt_upload_logs (channel_slug, event, detail) VALUES ("
        f"{_sql_literal(slug)}, {_sql_literal(event)}, {detail});"
    )
    ok, _ = _run_sql(query)
    return ok


def mirror_upload(record):
    """Mirror one registry record into yt_uploads. Best-effort.

    `record` is the dict appended to uploads/registry.json. The
    (file_sha256, channel_slug) unique constraint makes this
    idempotent: a re-mirror updates the row instead of duplicating it.
    """
    if not enabled():
        return False
    cols = [
        ("file_sha256", record.get("file_hash")),
        ("channel_slug", record.get("slug")),
        ("filename", record.get("file_name")),
        ("title", record.get("title")),
        ("youtube_video_id", record.get("video_id")),
        ("status", record.get("status")),
        ("privacy", record.get("privacy_status")),
        ("publish_at", record.get("publish_at_utc")),
        ("is_shorts", record.get("is_short")),
        ("duration_seconds", None),
    ]
    names = ", ".join(c for c, _ in cols)
    values = ", ".join(_sql_literal(v) for _, v in cols)
    query = (
        f"INSERT INTO public.yt_uploads ({names}) VALUES ({values}) "
        "ON CONFLICT (file_sha256, channel_slug) DO UPDATE SET "
        "filename = EXCLUDED.filename, title = EXCLUDED.title, "
        "youtube_video_id = EXCLUDED.youtube_video_id, status = EXCLUDED.status, "
        "privacy = EXCLUDED.privacy, publish_at = EXCLUDED.publish_at, "
        "is_shorts = EXCLUDED.is_shorts;"
    )
    ok, _ = _run_sql(query)
    return ok


def check_connection():
    """Read-only proof the mirror path works. Returns (ok, detail)."""
    ok, data = _run_sql(
        "SELECT (SELECT count(*) FROM public.yt_channels) AS channels, "
        "(SELECT count(*) FROM public.yt_uploads) AS uploads, "
        "(SELECT count(*) FROM public.yt_upload_logs) AS logs;",
        read_only=True,
    )
    if not ok:
        return False, data
    rows = data.get("result", [])
    return True, rows[0] if rows else {}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "check":
        ok, detail = check_connection()
        print(json.dumps({"ok": ok, "detail": detail}, indent=2))
        sys.exit(0 if ok else 1)
    print("usage: python3 supabase_backend.py check")
    sys.exit(2)
