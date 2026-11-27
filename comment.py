#!/usr/bin/env python3
"""Post a first (top-level) comment on a just-uploaded video, as the uploading channel.

Usage:
    venv/bin/python comment.py --channel <slug> --video-id <id> --text "..."

Top-level comments use commentThreads.insert (comments.insert is only for
replies). Both comment endpoints require ONLY the
https://www.googleapis.com/auth/youtube.force-ssl scope - the plain
https://www.googleapis.com/auth/youtube scope is NOT accepted (403
insufficientPermissions). The channel's token must carry the
youtube.force-ssl scope - add it to the OAuth consent screen and
re-authorize the channel before using this script.
Reuses the uploader's token loading + destination safety check, so a
comment can never be posted from the wrong channel. One call costs
50 quota units (general 10,000/day pool). Pinning a comment is not
possible via the API - pin it in YouTube Studio if wanted.
"""
import argparse
import sys

from uploader import (
    API_URL,
    UploadError,
    _request_with_retry,
    get_channel,
    load_credentials,
    log_event,
    verify_destination,
)


def post_comment(slug, video_id, text):
    creds = load_credentials(slug)
    verify_destination(slug, creds)
    channel_id = get_channel(slug)["channel_id"]
    resp = _request_with_retry(
        "POST",
        f"{API_URL}/commentThreads",
        params={"part": "snippet"},
        headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        },
        json={
            "snippet": {
                "channelId": channel_id,
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": text}},
            }
        },
    )
    if resp.status_code not in (200, 201):
        raise UploadError(f"commentThreads.insert failed: HTTP {resp.status_code}: {resp.text[:500]}")
    thread_id = resp.json()["id"]
    log_event(slug, "comment_posted", video_id=video_id, comment_thread_id=thread_id)
    return thread_id


def main():
    parser = argparse.ArgumentParser(description="Post a comment on a video")
    parser.add_argument("--channel", required=True, help="channel slug from channels.json")
    parser.add_argument("--video-id", required=True, help="YouTube video ID")
    parser.add_argument("--text", required=True, help="comment text")
    args = parser.parse_args()
    try:
        comment_id = post_comment(args.channel, args.video_id, args.text)
    except UploadError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"COMMENTED: {comment_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
