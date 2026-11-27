#!/usr/bin/env python3
"""Post the first comment on each video listed in a results file,
using the comment text from the batch manifest.

Usage:
    venv/bin/python comment_all.py --batch batch.json --results results.json

Reads video IDs from the results file, posts via commentThreads.insert
(comment.py), and writes the returned thread ID back into the results
file after each success. Skips videos that already have a comment_id.
A failure on one video is recorded and the run continues with the next;
exit code is 0 only if every video has a comment.

Comments only work on public or unlisted videos - YouTube refuses
comments on private videos. Publish first (see publish_all.py).
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from comment import post_comment  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", default="batch.json",
                        help="batch manifest JSON with the comment text per video key")
    parser.add_argument("--results", default="results.json",
                        help="results JSON with the video IDs (updated in place)")
    args = parser.parse_args()
    batch = json.loads(Path(args.batch).read_text())
    results_path = Path(args.results)
    data = json.loads(results_path.read_text())
    results = data["results"]
    done = 0
    failed = 0
    for res in results:
        if res.get("comment_id"):
            done += 1
            continue
        text = batch[res["video"]]["comment"]
        try:
            thread_id = post_comment(res["channel"], res["video_id"], text)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {res['channel']}/{res['video']} {res['video_id']}: {exc}", flush=True)
            data.setdefault("failures", []).append(
                {"channel": res["channel"], "video": res["video"],
                 "video_id": res["video_id"], "stage": "comment",
                 "error": str(exc)}
            )
            results_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            continue
        res["comment_id"] = thread_id
        results_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        done += 1
        print(f"  OK {res['channel']}/{res['video']} {res['video_id']} thread={thread_id}", flush=True)
    print(f"DONE: {done}/{len(results)} commented, {failed} failed")
    return 0 if failed == 0 and done == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
