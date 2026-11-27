"""Verify one YouTube OAuth refresh token per channel.

Usage (after the OAuth flows have been run, one per channel):
    python3 verify_channels.py
    python3 verify_channels.py --channel my-channel

Each token file lives at tokens/<slug>.json (mode 600, never in chat,
docs, logs or memory) and holds the authorized-user credentials for
that channel's OAuth flow: client_id, client_secret, refresh_token,
scopes. The script refreshes the access token if expired, calls
channels.list(part=snippet,contentDetails, mine=true), and checks the
returned channel id / title / handle against channels.json.

No video is uploaded or published by this script. A token that returns
a different channel is reported as MISMATCH, not silently accepted.
Exit code 0 only when every checked token matches its expected channel.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKENS_DIR = HERE / "tokens"
CHANNELS_FILE = HERE / "channels.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def load_expected():
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        return json.load(f)["channels"]


def verify_one(expected):
    slug = expected["slug"]
    token_path = TOKENS_DIR / f"{slug}.json"
    if not token_path.exists():
        return {"slug": slug, "name": expected["name"], "status": "pending",
                "detail": "no token file yet - OAuth flow not run for this channel"}
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        import requests
    except ImportError as exc:
        return {"slug": slug, "name": expected["name"], "status": "error",
                "detail": f"missing dependency: {exc} (pip install google-auth-oauthlib requests)"}
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                return {"slug": slug, "name": expected["name"], "status": "fail",
                        "detail": "token invalid and cannot refresh - re-run OAuth for this channel"}
        # Use requests (respects the proxy) instead of googleapiclient/httplib2,
        # which failed here with SSL WRONG_VERSION_NUMBER.
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet,contentDetails", "mine": "true"},
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if len(items) != 1:
            return {"slug": slug, "name": expected["name"], "status": "fail",
                    "detail": f"channels.list mine=true returned {len(items)} channels, expected 1"}
        ch = items[0]
        title = ch["snippet"]["title"]
        handle = ch["snippet"].get("customUrl", "")
        ok = title == expected["name"]
        return {"slug": slug, "name": expected["name"], "status": "ok" if ok else "mismatch",
                "detail": f"channelId={ch['id']} title={title!r} handle={handle!r}"
                          + ("" if ok else f" - expected title {expected['name']!r}")}
    except Exception as exc:  # noqa: BLE001 - report, do not leak tokens
        return {"slug": slug, "name": expected["name"], "status": "fail",
                "detail": f"{type(exc).__name__}: {exc}"}


def main(argv):
    only = None
    if len(argv) > 2 and argv[1] == "--channel":
        only = argv[2]
    expected_list = load_expected()
    if only:
        expected_list = [c for c in expected_list if c["slug"] == only]
        if not expected_list:
            print(f"unknown channel slug: {only}")
            return 2
    results = [verify_one(c) for c in expected_list]
    for r in results:
        print(f"{r['status'].upper():9} {r['name']} ({r['slug']}): {r['detail']}")
    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_pending = sum(1 for r in results if r["status"] == "pending")
    print(f"\n{n_ok}/{len(results)} verified, {n_pending} pending")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
