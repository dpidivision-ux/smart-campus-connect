"""Assemble final demo video: title cards + recorded segments + narration WAVs.
Usage: python3 demo/assemble.py [audio_dir]  (expects n<i>.wav for segment i)
Final mode requires every narration file; --preview skips missing narration.
Each segment gets a 1.2s tail pad (freeze frame + audio silence) for breathing room.
"""
import argparse, os, shutil, subprocess, sys, tempfile

FFMPEG = shutil.which("ffmpeg")
TAIL = 0.45
OUT = "video/out"
os.makedirs(OUT, exist_ok=True)

PARTS = {
    1: ("card", "video/cards/s1-title.png"),
    2: ("seg", "video/segs/s2.webm"),
    3: ("seg", "video/segs/e1.webm"),
    4: ("seg", "video/segs/s3.webm"),
    5: ("seg", "video/segs/s4.webm"),
    6: ("seg", "video/segs/e3.webm"),
    7: ("seg", "video/segs/s5.webm"),
    8: ("seg", "video/segs/e2.webm"),
    9: ("seg", "video/segs/e4.webm"),
    10: ("card", "video/cards/s6-close.png"),
}

def dur(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_format", path], capture_output=True, text=True)
    import json
    return float(json.loads(r.stdout)["format"]["duration"])

def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)

def build_part(i, kind, src, wav, out):
    target = max(dur(wav), dur(src) if kind == "seg" else 0) + TAIL
    if kind == "card":
        run([FFMPEG, "-y", "-loop", "1", "-i", src, "-i", wav,
             "-vf", "scale=1920:1080,format=yuv420p",
             "-af", f"apad=whole_dur={target}",
             "-t", str(target), "-r", "30",
             "-c:v", "libx264", "-preset", "fast", "-crf", "20",
             "-c:a", "aac", "-ar", "48000", out])
    else:
        vd = dur(src)
        # Preserve natural action speed. Freeze only after footage ends.
        pad = max(0.0, target - vd)
        vf = f"setpts=PTS-STARTPTS,fps=30,scale=1920:1080,format=yuv420p,tpad=stop_mode=clone:stop_duration={pad}"
        run([FFMPEG, "-y", "-i", src, "-i", wav,
             "-vf", vf, "-af", f"apad=whole_dur={target}",
             "-t", str(target), "-r", "30",
             "-c:v", "libx264", "-preset", "fast", "-crf", "20",
             "-c:a", "aac", "-ar", "48000", out])
    return target

def main(audio_dir, preview=False):
    missing = [i for i in PARTS if not os.path.exists(f"{audio_dir}/n{i}.wav")]
    if missing and not preview:
        raise SystemExit(f"Final render blocked: missing narration segments {missing}. Use --preview for an internal incomplete cut.")
    global OUT
    OUT = "video/out/preflight" if preview else "video/out/final"
    os.makedirs(OUT, exist_ok=True)
    parts, total = [], 0.0
    for i in sorted(PARTS):
        wav = f"{audio_dir}/n{i}.wav"
        if not os.path.exists(wav):
            print(f"skip seg {i}: no narration")
            continue
        kind, src = PARTS[i]
        out = f"{OUT}/p{i}.mp4"
        t = build_part(i, kind, src, wav, out)
        print(f"seg {i}: {t:.1f}s")
        parts.append(out); total += t
    lst = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    for p in parts:
        lst.write(f"file '{os.path.abspath(p)}'\n")
    lst.close()
    final = f"{OUT}/smart-campus-connect-{'INCOMPLETE-PREVIEW' if preview else 'demo'}.mp4"
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", lst.name,
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-c:a", "aac", "-ar", "48000", final])
    print(f"FINAL {final}  {total:.1f}s ({total/60:.2f} min)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_dir", nargs="?", default="video/audio")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    main(args.audio_dir, args.preview)
