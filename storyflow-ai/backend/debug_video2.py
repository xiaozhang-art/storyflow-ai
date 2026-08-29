"""Run the exact xfade_stitch command for 50 clips, print FULL stderr."""
import glob
import json
import subprocess
import sys

sys.path.insert(0, ".")
from runtime.montage.ffmpeg_ops import FFmpegOps

STORY = "8ad45d6c-4e70-4b92-8884-7500f2973209"
clips = sorted(glob.glob(f"storage/stories/{STORY}/video_clips/*.mp4"))
print(f"clips: {len(clips)}")
probes = [FFmpegOps.probe(c) or {"duration": 5.0} for c in clips]
print("first duration:", probes[0].get("duration"))

n = len(clips)
input_args = []
for clip in clips:
    input_args.extend(["-i", clip])

video_filters, audio_filters = [], []
cumulative_offset = 0.0
for i in range(n - 1):
    clip_dur = probes[i].get("duration", 5.0)
    offset = round(cumulative_offset + clip_dur - 0.5, 3)
    offset = max(0, offset)
    v_in1 = "[0:v]" if i == 0 else f"[vfade{i-1}]"
    a_in1 = "[0:a]" if i == 0 else f"[afade{i-1}]"
    v_in2, a_in2 = f"[{i+1}:v]", f"[{i+1}:a]"
    v_out = f"[vfade{i}]" if i < n - 2 else "[vout]"
    a_out = f"[afade{i}]" if i < n - 2 else "[aout]"
    video_filters.append(f"{v_in1}{v_in2}xfade=transition=fade:duration=0.5:offset={offset}{v_out}")
    audio_filters.append(f"{a_in1}{a_in2}acrossfade=d=0.5{a_out}")
    cumulative_offset = offset

filter_complex = ";".join(video_filters + audio_filters)
print("filter_complex length:", len(filter_complex))
cmd = ["ffmpeg", "-y"] + input_args + ["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]",
       f"storage/stories/{STORY}/video/test_xfade.mp4"]
print("cmd length:", len(" ".join(cmd)))

r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
print("rc:", r.returncode)
if r.returncode != 0:
    print("=== FULL STDERR (tail) ===")
    print(r.stderr[-3000:])
