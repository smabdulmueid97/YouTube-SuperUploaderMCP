#!/usr/bin/env python3
"""Batch runner: upload several videos to several channels, with A/B
variant titles/thumbnails per channel, then post the first comment on
each video.

Usage:
    venv/bin/python run_batch.py --manifest batch.json --results results.json --stage pilot
    venv/bin/python run_batch.py --manifest batch.json --results results.json --stage rest
    venv/bin/python run_batch.py --manifest batch.json --results results.json --stage all

--stage pilot uploads the FIRST video in the manifest to the FIRST
channel (variant 0) and stops - run this first to prove the pipeline
works before the full batch. --stage rest uploads everything else.
--stage all does pilot + rest in one go.

Manifest format (see batch.example.json):
    {"channels": ["my-channel", "my-second-channel"],
     "variant_map": [0, 1],
     "short": {"file": "short.mp4", "description": "...", "tags": "a,b",
               "comment": "First comment text",
               "variants": [{"title": "...", "thumbnail": "thumb-v1.jpg"},
                            {"title": "...", "thumbnail": "thumb-v2.jpg"}]},
     "full": {...}}

variant_map[i] picks which variant channel i gets. Results are written
to the results file as {"results": [...], "failures": [...]}.
One retry after ~30s on a transient failure; never loops forever.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from uploader import UploadError, load_registry, upload_video  # noqa: E402
from comment import post_comment  # noqa: E402

RETRY_WAIT_S = 30


def load_batch(path):
    return json.loads(Path(path).read_text())


def load_results(path):
    path = Path(path)
    if path.exists():
        return json.loads(path.read_text())
    return {"results": [], "failures": []}


def save_results(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def split_tags(tags_str):
    return [t.strip() for t in tags_str.split(",") if t.strip()]


def already_done(data, channel, video_key):
    return any(
        r["channel"] == channel and r["video"] == video_key for r in data["results"]
    )


def registry_entry_for(channel_slug, video_path):
    """Return the registry record for this slug+file, if it exists."""
    from uploader import sha256_file

    file_hash = sha256_file(video_path)
    registry = load_registry()
    for rec in registry.get("uploads", []):
        if rec.get("slug") == channel_slug and rec.get("file_hash") == file_hash:
            return rec
    return None


def do_one(batch, video_key, channel, data, results_path, skip_comments=False):
    """Upload one video to one channel + post its comment (unless skipped).
    Returns result dict or records a failure and returns None. Retries once
    after ~30s."""
    spec = batch[video_key]
    idx = batch["channels"].index(channel)
    variant_idx = batch["variant_map"][idx]
    variant = spec["variants"][variant_idx]
    tags = split_tags(spec["tags"])
    title = variant["title"]

    video_id = None
    video_url = None
    last_error = None
    for attempt in (1, 2):
        try:
            result = upload_video(
                channel,
                spec["file"],
                title,
                description=spec["description"],
                tags=tags,
                thumbnail=variant["thumbnail"],
                privacy="private",
            )
            video_id = result["video_id"]
            video_url = result["video_url"]
            last_error = None
            break
        except UploadError as exc:
            last_error = str(exc)
            print(f"  [{channel}/{video_key}] attempt {attempt} FAILED: {exc}", flush=True)
            # Guard against a half-finished first attempt: if the video
            # actually landed and was registered, reuse it instead of
            # uploading a second copy.
            rec = registry_entry_for(channel, spec["file"])
            if rec:
                print(f"  [{channel}/{video_key}] found in registry as {rec['video_id']}; reusing", flush=True)
                video_id = rec["video_id"]
                video_url = rec["video_url"]
                last_error = None
                break
            if attempt == 1:
                print(f"  retrying in {RETRY_WAIT_S}s ...", flush=True)
                time.sleep(RETRY_WAIT_S)
    if last_error is not None:
        data["failures"].append(
            {"channel": channel, "video": video_key, "variant": variant_idx,
             "title": title, "stage": "upload", "error": last_error}
        )
        save_results(results_path, data)
        return None

    # Post the first comment (retry once on failure; a comment failure
    # does not invalidate the upload).
    comment_id = None
    if skip_comments:
        print(f"  [{channel}/{video_key}] comment skipped (--skip-comments)", flush=True)
    else:
        comment_error = None
        for attempt in (1, 2):
            try:
                comment_id = post_comment(channel, video_id, spec["comment"])
                comment_error = None
                break
            except Exception as exc:  # noqa: BLE001
                comment_error = str(exc)
                print(f"  [{channel}/{video_key}] comment attempt {attempt} FAILED: {exc}", flush=True)
                if attempt == 1:
                    time.sleep(RETRY_WAIT_S)
        if comment_error is not None:
            data["failures"].append(
                {"channel": channel, "video": video_key, "variant": variant_idx,
                 "title": title, "stage": "comment", "video_id": video_id,
                 "video_url": video_url, "error": comment_error}
            )

    result = {
        "channel": channel,
        "video": video_key,
        "variant": variant_idx,
        "title": title,
        "video_id": video_id,
        "video_url": video_url,
        "comment_id": comment_id,
    }
    data["results"].append(result)
    save_results(results_path, data)
    print(f"  [{channel}/{video_key}] OK video={video_id} comment={comment_id}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="batch.json",
                        help="batch manifest JSON (see batch.example.json)")
    parser.add_argument("--results", default="results.json",
                        help="results JSON written by this run (created if missing)")
    parser.add_argument("--stage", choices=["pilot", "rest", "all"], required=True)
    parser.add_argument("--skip-comments", action="store_true",
                        help="upload + thumbnail only; skip the first-comment step "
                             "(use if the tokens lack the youtube.force-ssl scope)")
    args = parser.parse_args()
    batch = load_batch(args.manifest)
    data = load_results(args.results)
    channels = batch["channels"]
    video_keys = [k for k in batch if k not in ("channels", "variant_map")]
    pilot_video, pilot_channel = video_keys[0], channels[0]

    if args.stage in ("pilot", "all"):
        print(f"PILOT: {pilot_video} -> {pilot_channel} (variant 0)", flush=True)
        if already_done(data, pilot_channel, pilot_video):
            print("  pilot already done, skipping", flush=True)
        else:
            res = do_one(batch, pilot_video, pilot_channel, data, args.results,
                         skip_comments=args.skip_comments)
            if res is None:
                print("PILOT FAILED twice - stopping entirely", flush=True)
                return 1
        print("PILOT SUCCEEDED", flush=True)

    if args.stage in ("rest", "all"):
        # Every (video, channel) pair except the pilot pair, in manifest order.
        jobs = [(vk, ch) for vk in video_keys for ch in channels
                if (vk, ch) != (pilot_video, pilot_channel)]
        for video_key, channel in jobs:
            if already_done(data, channel, video_key):
                print(f"SKIP (already done): {video_key} -> {channel}", flush=True)
                continue
            print(f"UPLOAD: {video_key} -> {channel}", flush=True)
            do_one(batch, video_key, channel, data, args.results,
                   skip_comments=args.skip_comments)

    print(f"DONE: {len(data['results'])} succeeded, {len(data['failures'])} failures", flush=True)
    return 0 if not data["failures"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
