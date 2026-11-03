"""Assemble final demo video: title cards + recorded segments + narration WAVs.
Usage: python3 demo/assemble.py [audio_dir]  (expects n<i>.wav for segment i)
Segments with a missing WAV are skipped (e.g. seg4 held for live-model outcome).
Each segment gets a 1.2s tail pad (freeze frame + audio silence) for breathing room.
"""
import os, shutil, subprocess, sys, tempfile

FFMPEG = shutil.which("ffmpeg")
TAIL = 1.2
OUT = "video/out"
os.makedirs(OUT, exist_ok=True)

PARTS = {  # segment index -> ("card", png) or ("seg", webm)
    1: ("card", "video/cards/s1-title.png"),
    2: ("seg", "video/segs/s2.webm"),
    3: ("seg", "video/segs/s3.webm"),
    4: ("seg", "video/segs/s4.webm"),
    5: ("seg", "video/segs/s5.webm"),
    6: ("card", "video/cards/s6-close.png"),
}

def dur(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_format", path], capture_output=True, text=True)
    import json
    return float(json.loads(r.stdout)["format"]["duration"])

def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)

def build_part(i, kind, src, wav, out):
    target = dur(wav) + TAIL
    if kind == "card":
        run([FFMPEG, "-y", "-loop", "1", "-i", src, "-i", wav,
             "-vf", "scale=1920:1080,format=yuv420p",
             "-af", f"apad=whole_dur={target}",
             "-t", str(target), "-r", "30",
             "-c:v", "libx264", "-preset", "fast", "-crf", "20",
             "-c:a", "aac", "-ar", "48000", out])
    else:
        vd = dur(src)
        ratio = target / vd
        vf = f"setpts={ratio}*PTS,fps=30,scale=1920:1080,format=yuv420p"
        run([FFMPEG, "-y", "-i", src, "-i", wav,
             "-vf", vf, "-af", f"apad=whole_dur={target}",
             "-t", str(target), "-r", "30",
             "-c:v", "libx264", "-preset", "fast", "-crf", "20",
             "-c:a", "aac", "-ar", "48000", out])
    return target

def main(audio_dir):
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
    final = f"{OUT}/smart-campus-connect-demo.mp4"
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", lst.name,
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-c:a", "aac", "-ar", "48000", final])
    print(f"FINAL {final}  {total:.1f}s ({total/60:.2f} min)")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "video/audio")
