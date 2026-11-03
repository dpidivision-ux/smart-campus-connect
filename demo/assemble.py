"""Assemble final demo video: title cards + recorded segments + narration WAVs.
Usage: python3 demo/assemble.py <audio_dir>   (expects n1.wav..n6.wav)
Cards (s1,s6) become still videos of narration length; recorded segments are
slowed (setpts) or freeze-padded (tpad) to match their narration length.
"""
import os, subprocess, sys, tempfile

FFMPEG = os.path.expanduser(
    "~/.cache/ms-playwright/ffmpeg-1013/ffmpeg-linux")
OUT = "video/out"
os.makedirs(OUT, exist_ok=True)

def dur(path):
    r = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "Duration" in line:
            t = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = t.split(":")
            return int(h)*3600 + int(m)*60 + float(s)
    raise RuntimeError("no duration for " + path)

def run(cmd):
    subprocess.run(cmd, check=True)

def card_to_video(png, wav, out):
    d = dur(wav)
    run([FFMPEG, "-y", "-loop", "1", "-i", png, "-i", wav,
         "-vf", "scale=1920:1080,format=yuv420p", "-t", str(d),
         "-c:v", "libx264", "-c:a", "aac", "-ar", "48000",
         "-shortest", out])

def seg_to_video(webm, wav, out):
    vd, ad = dur(webm), dur(wav)
    if vd >= ad - 0.2:
        vf = "setpts=1.0*PTS,scale=1920:1080,format=yuv420p"
        t = ad
    else:
        ratio = ad / vd
        if ratio <= 1.6:  # slow down
            vf = f"setpts={ratio}*PTS,scale=1920:1080,format=yuv420p"
            t = ad
        else:  # freeze last frame for the remainder
            vf = ("setpts=1.0*PTS,tpad=stop_mode=clone:stop="
                  f"{ad - vd},scale=1920:1080,format=yuv420p")
            t = ad
    run([FFMPEG, "-y", "-i", webm, "-i", wav, "-vf", vf, "-t", str(t),
         "-c:v", "libx264", "-c:a", "aac", "-ar", "48000",
         "-shortest", out])

def main(audio_dir):
    parts = []
    card_to_video("video/cards/s1-title.png", f"{audio_dir}/n1.wav", f"{OUT}/p1.mp4"); parts.append(f"{OUT}/p1.mp4")
    for i, seg in [(2, "s2"), (3, "s3"), (4, "s4"), (5, "s5")]:
        seg_to_video(f"video/segs/{seg}.webm", f"{audio_dir}/n{i}.wav", f"{OUT}/p{i}.mp4"); parts.append(f"{OUT}/p{i}.mp4")
    card_to_video("video/cards/s6-close.png", f"{audio_dir}/n6.wav", f"{OUT}/p6.mp4"); parts.append(f"{OUT}/p6.mp4")
    lst = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    for p in parts:
        lst.write(f"file '{os.path.abspath(p)}'\n")
    lst.close()
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", lst.name,
         "-c", "copy", f"{OUT}/smart-campus-connect-demo.mp4"])
    print("final duration:", dur(f"{OUT}/smart-campus-connect-demo.mp4"), "s")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "video/audio")
