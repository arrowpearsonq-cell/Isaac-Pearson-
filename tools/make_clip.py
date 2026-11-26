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
  overlay   optional {"path": png/webp, "position": "bottom-right"|"bottom-left", "width": 0.3}
            image shown the whole clip in a lower corner, below the video
  punch     optional {"t": out_sec, "dur": 1.0, "scale": 1.25} punch-in zoom on the video
  freeze    optional {"t": out_sec, "dur": 0.5, "text": "NO WAY"} freeze-frame + text pop
            (t is on the cut timeline BEFORE the freeze is inserted)
  endcard   optional {"text": "Follow for daily GTA 6 clips", "dur": 1.5} end card appended
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

    hook = "".join(ch for ch in spec.get("hook", "") if ord(ch) < 0x2000).strip()  # font has no emoji
    if hook:
        room = video_top - 80 - 120  # space between top safe area and the credit line
        size = 72
        while True:
            f = font(HOOK_FONT, size, 800)
            lines = wrap(d, hook, f, W - 200)
            line_h = int(size * 1.22)
            pad_x, pad_y = 34, 16
            block_h = len(lines) * (line_h + 2 * pad_y - 10)
            if (len(lines) <= 3 and block_h <= room) or size <= 40:
                break
            size -= 4
        y = max(120, video_top - 80 - block_h)
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


def text_pop_png(text, path, size=130):
    img = Image.new("RGBA", (W, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(CAP_FONT, size)
    while d.textlength(text.upper(), font=f) > W - 120 and size > 60:
        size -= 8
        f = ImageFont.truetype(CAP_FONT, size)
    d.text((W / 2, 200), text.upper(), font=f, fill=(255, 196, 0), anchor="mm", stroke_width=12, stroke_fill=(0, 0, 0))
    img.save(path)


def endcard_png(text, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 215))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(CAP_FONT, 120)
    lines = wrap(d, text.upper(), f, W - 160)
    y = H / 2 - (len(lines) - 1) * 75
    for ln in lines:
        d.text((W / 2, y), ln, font=f, fill=(255, 255, 255), anchor="mm", stroke_width=10, stroke_fill=(0, 0, 0))
        y += 150
    img.save(path)


def logo_png(ov, video_top, vid_h, path):
    im = Image.open(ov["path"]).convert("RGBA")
    w = int(W * float(ov.get("width", 0.3)))
    h = int(im.height * w / im.width)
    im = im.resize((w, h), Image.LANCZOS)
    margin = 40
    x = margin if ov.get("position", "bottom-right") == "bottom-left" else W - w - margin
    y = min(H - h - 220, video_top + vid_h + 40)  # under the video, above the bottom UI
    y = max(y, video_top + vid_h + 10)
    im.save(path)
    return x, y


def main():
    spec_path = sys.argv[1]
    spec = json.load(open(spec_path))
    src = spec["source"]
    out = spec.get("output") or os.path.join(os.path.dirname(os.path.abspath(spec_path)), "clip.mp4")
    segs = spec["segments"]
    layout = spec.get("layout", "fit")

    if layout == "zoom":
        vid_w, vid_h = W, 1200                    # 9:10 crop
    else:
        vid_w, vid_h = W, int(W * 9 / 16) // 2 * 2  # 1080x608
    video_top = (H - vid_h) // 2 + (60 if layout == "fit" else 160)

    tmp = tempfile.mkdtemp()
    overlay = os.path.join(tmp, "overlay.png")
    make_overlay(spec, video_top, vid_h, overlay)

    # Trim + concat segments
    parts = []
    for i, (a, b) in enumerate(segs):
        parts.append(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS[v{i}];[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}];")
    n = len(segs)
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv0][ca0];"

    if layout == "zoom":
        fg = f"[cv]scale=-2:{vid_h},crop={vid_w}:{vid_h}[fg00];[cv2]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,eq=brightness=-0.15[bg];"
    else:
        fg = f"[cv]scale={vid_w}:{vid_h}[fg00];[cv2]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,eq=brightness=-0.15[bg];"
    total = sum(b - a for a, b in segs)
    fr = spec.get("freeze")
    pre = "[cv0]fps=30[cvf];"
    if fr:
        t, fd = float(fr["t"]), float(fr.get("dur", 0.5))
        t = min(max(t, 0.1), total - 0.1)
        pre = (f"[cv0]fps=30,split=3[x1][x2][x3];[x1]trim=0:{t:.3f},setpts=PTS-STARTPTS[p1];"
               f"[x2]trim=start={t:.3f}:duration=0.034,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={fd:.3f},trim=0:{fd:.3f}[p2];"
               f"[x3]trim=start={t:.3f},setpts=PTS-STARTPTS[p3];[p1][p2][p3]concat=n=3:v=1:a=0[cvf];"
               f"[ca0]aformat=sample_rates=44100:channel_layouts=stereo,asplit[y1][y3];[y1]atrim=0:{t:.3f},asetpts=PTS-STARTPTS[q1];"
               f"aevalsrc=0|0:s=44100:d={fd:.3f}[q2];[y3]atrim=start={t:.3f},asetpts=PTS-STARTPTS[q3];[q1][q2][q3]concat=n=3:v=0:a=1[caf];")
        total += fd
    else:
        pre += "[ca0]anull[caf];"
    caps = build_captions(spec, segs, tmp)
    if fr:
        caps = [(p, a + (fd if a >= t else 0), e + (fd if e > t else 0)) for p, a, e in caps]
    pu = spec.get("punch")
    if pu:
        ps, pd, sc = float(pu["t"]), float(pu.get("dur", 1.0)), float(pu.get("scale", 1.25))
        zw, zh = int(vid_w * sc) // 2 * 2, int(vid_h * sc) // 2 * 2
        fg += (f"[fg00]split[fa][fb];[fb]scale={zw}:{zh},crop={vid_w}:{vid_h}[fz];"
               f"[fa][fz]overlay=0:0:enable='gte(t,{ps:.3f})*lt(t,{ps + pd:.3f})'[fg0];")
    else:
        fg += "[fg00]null[fg0];"
    cap_y = video_top + vid_h - 130  # sits over the lower part of the video
    chain = f"[bg][fg0]overlay=(W-w)/2:{video_top}[base];[base][1:v]overlay=0:0[l0];"
    inputs = ["-i", src, "-i", overlay]
    last, k = "l0", 2

    def add(png, x, y, en=None):
        nonlocal chain, last, k
        inputs.extend(["-i", png])
        e = f":enable='{en}'" if en else ""
        chain += f"[{last}][{k}:v]overlay={x}:{y}{e}[l{k}];"
        last = f"l{k}"
        k += 1

    for png, s, e in caps:
        add(png, 0, cap_y, f"gte(t,{s:.3f})*lt(t,{e:.3f})")
    if spec.get("overlay") and os.path.exists(spec["overlay"].get("path", "")):
        lp = os.path.join(tmp, "logo.png")
        x, y = logo_png(spec["overlay"], video_top, vid_h, lp)
        add(lp, x, y)
    if fr and fr.get("text"):
        tp = os.path.join(tmp, "pop.png")
        text_pop_png(fr["text"], tp)
        add(tp, 0, video_top + vid_h // 2 - 200, f"gte(t,{t:.3f})*lt(t,{t + fd:.3f})")
    ec = spec.get("endcard")
    tail = ""
    if ec:
        ed = float(ec.get("dur", 1.5))
        chain += f"[{last}]tpad=stop_mode=clone:stop_duration={ed:.3f}[lt];"
        last = "lt"
        ep = os.path.join(tmp, "end.png")
        endcard_png(ec.get("text", "Follow for daily GTA 6 clips"), ep)
        add(ep, 0, 0, f"gte(t,{total:.3f})")
        tail = f"[caf]apad=pad_dur={ed:.3f}[ca];"
    else:
        tail = "[caf]anull[ca];"
    chain += f"[{last}]format=yuv420p[vout];" + tail
    chain = chain.rstrip(";")
    graph = "".join(parts) + concat + pre + "[cvf]split[cv][cv2];" + fg + chain

    cmd = ["ffmpeg", "-y", "-v", "error", *inputs,
           "-filter_complex", graph, "-map", "[vout]", "-map", "[ca]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    print(out)


if __name__ == "__main__":
    main()
