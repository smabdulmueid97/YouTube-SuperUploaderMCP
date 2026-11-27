"""Dashboard / summary of upload status for all 9 channels.

Reads channels.json (verified channel IDs), uploads/registry.json
(completed + scheduled uploads) and logs/<slug>.jsonl (per-channel
event logs) and prints a status table. With --verify it also checks
each OAuth token live (read-only channels.list).

Also writes dashboard.html - a static page you can open in a browser
with the same summary. No tokens are ever written into the dashboard.

Usage:
    python3 status.py
    python3 status.py --verify
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def read_log(slug):
    path = HERE / "logs" / f"{slug}.jsonl"
    if not path.exists():
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def main():
    parser = argparse.ArgumentParser(description="Upload status dashboard for all channels")
    parser.add_argument("--verify", action="store_true",
                        help="also verify each OAuth token live (read-only)")
    args = parser.parse_args()

    channels = load_json(HERE / "channels.json", {"channels": []})["channels"]
    registry = load_json(HERE / "uploads" / "registry.json", {"uploads": []})["uploads"]

    rows = []
    for ch in channels:
        slug = ch["slug"]
        uploads = [r for r in registry if r["slug"] == slug]
        uploaded = [r for r in uploads if r["status"] == "uploaded"]
        scheduled = [r for r in uploads if r["status"] == "scheduled"]
        events = read_log(slug)
        last = events[-1] if events else None
        token = ch.get("token_status", "pending")
        if args.verify:
            from uploader import load_credentials, verify_destination
            try:
                creds = load_credentials(slug)
                verify_destination(slug, creds)
                token = "ok (live check)"
            except Exception as exc:  # noqa: BLE001 - show the failure in the table
                token = f"FAIL: {exc}"
        rows.append({
            "channel": ch["name"], "handle": ch["handle"], "channel_id": ch.get("channel_id", "-"),
            "token": token, "uploaded": len(uploaded), "scheduled": len(scheduled),
            "shorts": sum(1 for r in uploads if r.get("is_short")),
            "last_event": f"{last['ts'][:19]} {last['event']}" if last else "none yet",
            "last_video": uploaded[-1]["video_url"] if uploaded else (scheduled[-1]["video_url"] if scheduled else "-"),
        })

    print(f"{'Channel':28} {'Token':14} {'Up':>3} {'Sch':>3} {'Shorts':>6}  Last event")
    print("-" * 110)
    for r in rows:
        print(f"{r['channel'][:28]:28} {str(r['token'])[:14]:14} {r['uploaded']:>3} {r['scheduled']:>3} {r['shorts']:>6}  {r['last_event']}")
    print("-" * 110)
    print(f"Total uploaded: {sum(r['uploaded'] for r in rows)}  "
          f"scheduled: {sum(r['scheduled'] for r in rows)}  "
          f"channels: {len(rows)}")
    print("Note: videos.insert has its own bucket - 100 uploads/day per project (1 unit each).")
    print("9 uploads/day fits inside the default allowance; no quota increase needed.")

    # Static HTML dashboard (no tokens inside).
    html_rows = ""
    for r in rows:
        link = "-" if r["last_video"] == "-" else '<a href="' + r["last_video"] + '">watch</a>'
        html_rows += (
            f"<tr><td>{r['channel']}</td><td>{r['handle']}</td><td><code>{r['channel_id']}</code></td>"
            f"<td>{r['token']}</td><td>{r['uploaded']}</td><td>{r['scheduled']}</td>"
            f"<td>{r['shorts']}</td><td>{r['last_event']}</td><td>{link}</td></tr>"
        )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>YouTube-SuperUploaderMCP - Dashboard</title>
<style>body{{font-family:sans-serif;max-width:1100px;margin:2em auto;padding:0 1em}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:6px 8px;text-align:left}}
th{{background:#f0f0f0}}code{{font-size:12px}}</style></head>
<body><h1>YouTube-SuperUploaderMCP - Dashboard</h1>
<p>Generated {datetime.now(timezone.utc).isoformat()} UTC. Tokens are never shown here.</p>
<table><tr><th>Channel</th><th>Handle</th><th>Channel ID</th><th>Token</th>
<th>Uploaded</th><th>Scheduled</th><th>Shorts</th><th>Last event</th><th>Last video</th></tr>
{html_rows}</table>
<p>videos.insert has its own bucket: 100 uploads/day per project (1 unit each).
9 uploads/day fits inside the default allowance; no quota increase needed.</p>
</body></html>"""
    (HERE / "dashboard.html").write_text(html, encoding="utf-8")
    print("\nWrote dashboard.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
