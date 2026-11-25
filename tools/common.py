import json, os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "sources")
os.makedirs(SRC, exist_ok=True)
_model = None


def ytdlp_json(url, flat=False):
    cmd = ["yt-dlp", "-J", "--no-warnings"] + (["--flat-playlist"] if flat else []) + [url]
    return json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)


def download(url, name):
    out = os.path.join(SRC, f"{name}.mp4")
    if not os.path.exists(out):
        subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "b[height<=1080]/bv*[height<=1080]+ba/b",
                        "--merge-output-format", "mp4", "-o", out, url], check=True)
    return out


def duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip())


def transcribe(path, start=None, end=None):
    """Writes <path>.words.json ([[s,e,word],...]) and returns (words, readable text)."""
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    import numpy as np
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", str(start), "-to", str(end)] if start is not None else []) + \
          ["-i", path, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    audio = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)
    off = start or 0
    words, lines = [], []
    try:
        segs, _ = _model.transcribe(audio, word_timestamps=True, vad_filter=True)
        for s in segs:
            lines.append(f"[{s.start + off:.1f}s] {s.text.strip()}")
            for w in s.words or []:
                words.append([round(w.start + off, 2), round(w.end + off, 2), w.word.strip()])
    except Exception as e:  # faster-whisper word alignment can crash on odd audio; don't kill the whole run
        print("transcribe failed, skipping words:", path, e)
        words, lines = [], []
        try:
            segs, _ = _model.transcribe(audio, word_timestamps=False, vad_filter=True)
            lines = [f"[{s.start + off:.1f}s] {s.text.strip()}" for s in segs]
        except Exception as e2:
            print("plain transcribe failed too:", e2)
    json.dump(words, open(os.path.splitext(path)[0] + ".words.json", "w"))
    return words, "\n".join(lines)
