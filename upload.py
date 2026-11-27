"""Command line for the reusable YouTube upload engine.

Examples (all dry-run first - nothing is published):
    python3 upload.py --channel nemonit --video test.mp4 --title "Test" --dry-run
    python3 upload.py --channel nemonit --video short.mp4 --title "T" --tags a,b \\
        --thumbnail thumb.jpg --publish-at "2026-11-28 18:00" --dry-run

Remove --dry-run ONLY for the one approved test video. Never run a
real upload without the user's approval for that video.
"""
import argparse
import json
import sys

from uploader import UploadError, upload_video


def main():
    parser = argparse.ArgumentParser(description="Upload one video to one YouTube channel")
    parser.add_argument("--channel", required=True, help="channel slug from channels.json")
    parser.add_argument("--video", required=True, help="path to the video file")
    parser.add_argument("--title", required=True, help="video title (max 100 chars)")
    parser.add_argument("--description", default="", help="video description (max 5000 chars)")
    parser.add_argument("--tags", default="", help="comma-separated tags (max 30)")
    parser.add_argument("--thumbnail", default=None, help="path to thumbnail image (<2 MB)")
    parser.add_argument("--publish-at", default=None,
                        help="scheduled publish time 'YYYY-MM-DD HH:MM' in Asia/Dhaka")
    parser.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"],
                        help="privacy for immediate publish (scheduled videos are private until publish time)")
    parser.add_argument("--shorts", action="store_true", help="mark as a Short (auto-detected otherwise)")
    parser.add_argument("--force", action="store_true", help="re-upload even if this file was already uploaded")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate everything, show the exact request, upload NOTHING")
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    try:
        result = upload_video(
            slug=args.channel,
            video_path=args.video,
            title=args.title,
            description=args.description,
            tags=tags,
            thumbnail=args.thumbnail,
            publish_at=args.publish_at,
            privacy=args.privacy,
            force_shorts=True if args.shorts else None,
            force=args.force,
            dry_run=args.dry_run,
        )
    except UploadError as exc:
        print(f"ERROR: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - show the real error, do not hide it
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1

    if result["dry_run"]:
        print("DRY RUN - nothing was uploaded. This is what WOULD be sent:")
        print(json.dumps(result["plan"], indent=2, ensure_ascii=False))
    else:
        print(f"UPLOADED: {result['video_url']}")
        print(f"video_id: {result['video_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
