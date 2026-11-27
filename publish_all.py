#!/usr/bin/env python3
"""Make every video listed in a results file public (or unlisted).

Usage:
    venv/bin/python publish_all.py --results results.json [--privacy public|unlisted]

Reads video IDs from the results file and flips each one with
videos.update via uploader.set_video_privacy (current status fetched
first, only privacyStatus changed, new value verified by a fresh read).
Progress is printed per video; a failure on one video is recorded and
the run continues. Exit code is 0 only if every video ends up with the
requested privacy. Run comment_all.py afterwards - YouTube only
accepts comments once a video is public/unlisted.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from uploader import set_video_privacy  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default="results.json",
                        help="results JSON with the video IDs")
    parser.add_argument("--privacy", choices=["public", "unlisted"], default="public")
    args = parser.parse_args()
    results_path = Path(args.results)
    data = json.loads(results_path.read_text())
    results = data["results"]
    done = 0
    failed = 0
    for res in results:
        try:
            out = set_video_privacy(res["channel"], res["video_id"], args.privacy)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {res['channel']}/{res['video']} {res['video_id']}: {exc}", flush=True)
            data.setdefault("failures", []).append(
                {"channel": res["channel"], "video": res["video"],
                 "video_id": res["video_id"], "stage": "publish",
                 "error": str(exc)}
            )
            results_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            continue
        done += 1
        print(f"  OK {res['channel']}/{res['video']} {res['video_id']} -> {args.privacy}"
              + ("" if out["changed"] else " (already)"), flush=True)
    print(f"DONE: {done}/{len(results)} {args.privacy}, {failed} failed")
    return 0 if failed == 0 and done == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
