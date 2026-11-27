"""Run one YouTube OAuth flow for a single channel and verify it.

Usage (one flow per channel):
    python3 auth_channel.py --channel my-channel

The user picks the channel in Google's chooser in the browser window
that opens. That choice decides which channel the token belongs to —
nothing in this script selects the channel.

Prerequisites (prepared, no secrets in this file):
  - A Desktop OAuth client for your Google Cloud project, with
    the YouTube Data API v3 + Analytics API enabled and yourself
    added as a test user while the consent screen is in Testing.
  - The client secrets file placed at client_secret.json next to this
    script (mode 600). This script never prints its contents.
  - channels.json listing the expected channel for each slug.

What it does:
  1. Runs the installed-app OAuth flow (localhost redirect,
     access_type=offline, prompt=consent) for the scopes in SCOPES.
  2. Saves the resulting credentials to tokens/<slug>.json (mode 600).
  3. Verifies that token with channels.list(mine=true) via
     verify_channels.py --channel <slug> and reports ok / mismatch.
No video is uploaded or published by this script.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIENT_SECRETS = HERE / "client_secret.json"
TOKENS_DIR = HERE / "tokens"
SCOPES = [
    # FULL YouTube permission set. All 7 YouTube Data API v3 scopes +
    # both YouTube Analytics API scopes = 9 total, including the two
    # youtubepartner scopes (CMS content partners only; unusable for a
    # regular account, but included so no feature ever needs another
    # re-authorization round).
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.channel-memberships.creator",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    "https://www.googleapis.com/auth/youtubepartner",
    "https://www.googleapis.com/auth/youtubepartner-channel-audit",
]


def expected_channel(slug):
    with open(HERE / "channels.json", encoding="utf-8") as f:
        channels = json.load(f)["channels"]
    for ch in channels:
        if ch["slug"] == slug:
            return ch
    return None


def main():
    parser = argparse.ArgumentParser(description="OAuth for one YouTube channel")
    parser.add_argument("--channel", required=True, help="channel slug from channels.json")
    args = parser.parse_args()
    expected = expected_channel(args.channel)
    if expected is None:
        print(f"unknown channel slug: {args.channel}")
        return 2
    if not CLIENT_SECRETS.exists():
        print("client_secret.json is missing next to this script. "
              "Place the Desktop OAuth client file there first (mode 600) and retry.")
        return 2
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        print(f"missing dependency: {exc} (pip install google-auth-oauthlib google-api-python-client)")
        return 2
    print(f"Starting OAuth for: {expected['name']} ({expected['handle']})")
    print("In the browser window that opens, sign in as the manager account")
    print("and pick exactly that channel in Google's channel chooser.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
    # No browser on this VM, so do not try to open one here. The URL is
    # printed by run_local_server; open it in the Muse browser instead
    # and pick the expected channel there.
    creds = flow.run_local_server(port=0, open_browser=False, access_type="offline", prompt="consent")
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    token_path = TOKENS_DIR / f"{args.channel}.json"
    token_path.write_text(creds.to_json(), encoding="utf-8")
    os.chmod(token_path, 0o600)
    print(f"Token saved for {expected['name']} (contents not shown). Verifying...")
    result = subprocess.run(
        [sys.executable, str(HERE / "verify_channels.py"), "--channel", args.channel],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
