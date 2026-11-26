#!/usr/bin/env python3
"""Render vertical clips from a list of jobs.

Env JOBS = JSON list, each job:
  {"name": "kai-jetski", "url": "<twitch clip / twitch VOD / youtube / kick url>",
   "segments": [[s, e], ...]   (optional; default = whole video),
   "hook": "...", "credit": "Clip: Kai Cenat on Twitch", "watermark": "@handle",
   "layout": "fit"|"zoom", "captions": "auto"|[] , "post_caption": "...", "tags": "#gta6 ...",
   "overlay": {"path": "assets/clipup.png" or "url": "https://...", "position": "bottom-right", "width": 0.3},
   "punch": {"t": 2.0, "dur": 1.0, "scale": 1.25}, "freeze": {"t": 1.0, "dur": 0.5, "text": "NO WAY"},
   "endcard": {"text": "Follow for daily GTA 6 clips", "dur": 1.5}}  (times are on the cut timeline)
Output: out/<name>.mp4 and out/<name>.txt
"""
import json, os, re, subprocess, sys, urllib.request
from common import download, duration, transcribe, ROOT

OUT = os.path.join(ROOT, "out")
os.makedirs(OUT, exist_ok=True)
jobs = json.loads(os.environ["JOBS"])
for j in jobs:
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", j["name"])
    src = download(j["url"], name)
    segs = j.get("segments") or [[0, round(duration(src), 2)]]
    caps = j.get("captions", "auto")
    if caps == "auto":  # only transcribe the part we use (VODs can be hours long)
        transcribe(src, min(s for s, _ in segs), max(e for _, e in segs))
    spec = {k: j[k] for k in ("hook", "credit", "watermark", "layout", "punch", "freeze", "endcard") if k in j}
    ov = j.get("overlay")
    if ov:
        ov = dict(ov)
        path = os.path.join(ROOT, ov.get("path") or "assets/clipup.webp")
        if not os.path.exists(path) and ov.get("url"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            req = urllib.request.Request(ov["url"], headers={"User-Agent": "Mozilla/5.0"})
            open(path, "wb").write(urllib.request.urlopen(req, timeout=60).read())
        ov["path"] = path
        spec["overlay"] = ov
    spec.update(source=src, segments=segs, captions=caps, output=os.path.join(OUT, f"{name}.mp4"))
    sp = os.path.join(OUT, f"{name}.spec.json")
    json.dump(spec, open(sp, "w"))
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_clip.py"), sp], check=True)
    open(os.path.join(OUT, f"{name}.txt"), "w").write(
        f"{j.get('post_caption', j.get('hook', ''))}\n\n{j.get('credit', '')}\n\n{j.get('tags', '#gta6 #fyp')}\n")
    print("rendered", name)
