#!/usr/bin/env python3
"""Render a vertical 1080x1920 TikTok/Shorts clip from a horizontal source using a JSON spec.

Usage: python3 make_clip.py spec.json

Spec keys:
  source    path to the source mp4 (horizontal, e.g. a stream VOD)
  output    output mp4 path (default: <spec dir>/clip.mp4)
  segments  [[start, end], ...] in source seconds, played in order (jump cuts)
  hook      on-screen hook text at the top, shown for the whole clip
  credit    small credit line above the video, e.g. "Clip: Tomo on YouTube"
  layout    "fit"  = full 16:9 frame over a blurred zoomed copy (default)
            "zoom" = center crop to 4:5 so the action is bigger on a phone
  watermark optional small handle at the bottom, e.g. "@gta6fieldguide"
  captions  optional [[src_start, src_end, "TWO WORDS"], ...] in source seconds;
            burned in big white Anton text, last word highlighted yellow
"""
import json, os, subprocess, sys, tempfile, textwrap
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
HOOK_FONT = os.environ.get("HOOK_FONT", f"{FONT_DIR}/Montserrat.ttf")
CREDIT_FONT = HOOK_FONT


def font(path, size, weight=800):
    f = ImageFont.truetype(path, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_overlay(spec, video_top, video_h, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    hook = spec.get("hook", "").strip()
    if hook:
        size = 72
        while True:
            f = font(HOOK_FONT, size, 800)
            lines = wrap(d, hook, f, W - 200)
            if len(lines) <= 3 or size <= 48:
                break
            size -= 4
        line_h = int(size * 1.22)
        pad_x, pad_y = 34, 16
        block_h = len(lines) * (line_h + 2 * pad_y)
        y = max(120, video_top - 110 - block_h)
        for ln in lines:
            tw = d.textlength(ln, font=f)
            x0 = (W - tw) / 2 - pad_x
            box = [x0, y, x0 + tw + 2 * pad_x, y + line_h + 2 * pad_y - 6]
            d.rounded_rectangle(box, radius=22, fill=(255, 255, 255, 255))
            d.text((W / 2, y + pad_y + line_h / 2 - 4), ln, font=f, fill=(0, 0, 0), anchor="mm")
            y += line_h + 2 * pad_y - 10

    credit = spec.get("credit", "").strip()
    if credit:
        f = font(CREDIT_FONT, 34, 600)
        d.text((W / 2, video_top - 34), credit, font=f, fill=(255, 255, 255, 230), anchor="mm",
               stroke_width=3, stroke_fill=(0, 0, 0, 200))

    wm = spec.get("watermark", "").strip()
    if wm:
        f = font(CREDIT_FONT, 38, 700)
        d.text((W / 2, min(H - 260, video_top + video_h + 90)), wm, font=f,
               fill=(255, 255, 255, 200), anchor="mm", stroke_width=3, stroke_fill=(0, 0, 0, 180))
    img.save(path)


CAP_FONT = f"{FONT_DIR}/Anton.ttf"


def caption_png(text, highlight, path):
    """Big centered caption: white words, one highlighted yellow, thick black outline."""
    img = Image.new("RGBA", (W, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(CAP_FONT, 96)
    words = text.upper().split()
    gap = 22
    widths = [d.textlength(w, font=f) for w in words]
    x = (W - (sum(widths) + gap * (len(words) - 1))) / 2
    for i, (w, ww) in enumerate(zip(words, widths)):
        col = (255, 196, 0) if i == highlight else (255, 255, 255)
        d.text((x, 130), w, font=f, fill=col, anchor="lm", stroke_width=9, stroke_fill=(0, 0, 0))
        x += ww + gap
    img.save(path)


def build_captions(spec, segs, tmp):
    """captions: [[src_start, src_end, "two words"], ...] in SOURCE seconds.
    Maps them onto the cut timeline. Returns [(png, out_start, out_end)]."""
    caps = spec.get("captions", [])
    if caps == "auto":  # build 1-3 word chunks from sources/<id>.words.json
        wpath = os.path.splitext(spec["source"])[0] + ".words.json"
        words = json.load(open(wpath)) if os.path.exists(wpath) else []
        caps, chunk = [], []
        for w in words:
            chunk.append(w)
            if len(chunk) == 3 or w[2][-1:] in ".,!?" or len(" ".join(c[2] for c in chunk)) > 14:
                caps.append([chunk[0][0], chunk[-1][1], " ".join(c[2] for c in chunk).strip(".,")])
                chunk = []
        if chunk:
            caps.append([chunk[0][0], chunk[-1][1], " ".join(c[2] for c in chunk)])
    out, offset, idx = [], 0.0, 0
    for a, b in segs:
        for cs, ce, txt in caps:
            s, e = max(cs, a), min(ce, b)
            if e <= s:
                continue
            hl = len(txt.split()) - 1 if spec.get("highlight_last", True) else -1
            p = os.path.join(tmp, f"cap{idx}.png")
            caption_png(txt, hl, p)
            out.append((p, offset + s - a, offset + e - a))
            idx += 1
        offset += b - a
    return out


def main():
    spec_path = sys.argv[1]
    spec = json.load(open(spec_path))
    src = spec["source"]
    out = spec.get("output") or os.path.join(os.path.dirname(os.path.abspath(spec_path)), "clip.mp4")
    segs = spec["segments"]
    layout = spec.get("layout", "fit")

    if layout == "zoom":
        vid_w, vid_h = W, int(W * 5 / 4)          # 1080x1350
    else:
        vid_w, vid_h = W, int(W * 9 / 16) // 2 * 2  # 1080x608
    video_top = (H - vid_h) // 2 + (60 if layout == "fit" else 120)

    tmp = tempfile.mkdtemp()
    overlay = os.path.join(tmp, "overlay.png")
    make_overlay(spec, video_top, vid_h, overlay)

    # Trim + concat segments
    parts = []
    for i, (a, b) in enumerate(segs):
        parts.append(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS[v{i}];[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}];")
    n = len(segs)
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ca];"

    if layout == "zoom":
        fg = f"[cv]scale=-2:{vid_h},crop={vid_w}:{vid_h}[fg0];[cv2]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,eq=brightness=-0.15[bg];"
    else:
        fg = f"[cv]scale={vid_w}:{vid_h}[fg0];[cv2]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,eq=brightness=-0.15[bg];"
    caps = build_captions(spec, segs, tmp)
    cap_y = video_top + vid_h - 130  # sits over the lower part of the video
    chain = f"[bg][fg0]overlay=(W-w)/2:{video_top}[base];[base][1:v]overlay=0:0[l0];"
    inputs = ["-i", src, "-i", overlay]
    last = "l0"
    for i, (png, s, e) in enumerate(caps):
        inputs += ["-i", png]
        chain += f"[{last}][{i + 2}:v]overlay=0:{cap_y}:enable='gte(t,{s:.3f})*lt(t,{e:.3f})'[l{i + 1}];"
        last = f"l{i + 1}"
    chain += f"[{last}]format=yuv420p[vout]"
    graph = "".join(parts) + concat + "[cv]split[cv][cv2];" + fg + chain

    cmd = ["ffmpeg", "-y", "-v", "error", *inputs,
           "-filter_complex", graph, "-map", "[vout]", "-map", "[ca]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    print(out)


if __name__ == "__main__":
    main()
