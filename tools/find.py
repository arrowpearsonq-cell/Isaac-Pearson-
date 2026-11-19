#!/usr/bin/env python3
"""Find the most-viewed moments from any Twitch streamer (their community clips),
download them, transcribe them and grab preview frames.

Env: STREAMERS="tomo,kaicenat"  RANGE=24hr|7d|30d|all  PER_STREAMER=5
Output: out/candidates.json + out/frames/<id>_<n>.jpg
"""
import json, os, subprocess
from common import ytdlp_json, download, duration, transcribe, ROOT

OUT = os.path.join(ROOT, "out")
os.makedirs(os.path.join(OUT, "frames"), exist_ok=True)
streamers = [s.strip().lstrip("@") for s in os.environ.get("STREAMERS", "").split(",") if s.strip()]
rng = os.environ.get("RANGE", "7d")
per = int(os.environ.get("PER_STREAMER", "5"))
query = os.environ.get("MATCH", "").lower()  # optional: only clips whose title contains this (e.g. "gta")

cands = []
for s in streamers:
    try:
        lst = ytdlp_json(f"https://www.twitch.tv/{s}/clips?filter=clips&range={rng}", flat=True)
    except subprocess.CalledProcessError as e:
        print("could not list", s, e.stderr[-300:] if e.stderr else "")
        continue
    entries = lst.get("entries", [])
    if query:
        entries = [e for e in entries if query in (e.get("title") or "").lower()]
    entries.sort(key=lambda e: e.get("view_count") or 0, reverse=True)
    for e in entries[:per]:
        cid = e.get("id") or e["url"].rstrip("/").split("/")[-1]
        url = e.get("url") or e.get("webpage_url")
        try:
            path = download(url, f"tw_{cid}")
        except subprocess.CalledProcessError:
            print("download failed", url)
            continue
        dur = duration(path)
        _, text = transcribe(path)
        for n, t in enumerate([dur * 0.2, dur * 0.5, dur * 0.8]):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                            "-vf", "scale=640:-1", os.path.join(OUT, "frames", f"tw_{cid}_{n}.jpg")])
        cands.append({"id": f"tw_{cid}", "url": url, "streamer": s, "title": e.get("title"),
                      "views": e.get("view_count"), "duration": round(dur, 1), "transcript": text})
        print(f"{s}: {e.get('title')} ({e.get('view_count')} views)")

json.dump(cands, open(os.path.join(OUT, "candidates.json"), "w"), indent=1)
print(len(cands), "candidates")
