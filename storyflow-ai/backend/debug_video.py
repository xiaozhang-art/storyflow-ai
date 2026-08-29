"""Reproduce montage compose failure with full ffmpeg stderr."""
import glob
import logging
import sys
import traceback

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from pathlib import Path
from runtime.montage.video_composer import VideoComposer, ComposeConfig

STORY = "8ad45d6c-4e70-4b92-8884-7500f2973209"
clips = sorted(glob.glob(f"storage/stories/{STORY}/video_clips/*.mp4"))
print(f"clips: {len(clips)}")

config = ComposeConfig(
    output_path=f"storage/stories/{STORY}/video/story.mp4",
    transition="crossfade",
    transition_duration=0.5,
    profile="storyflow_default",
    burn_subtitles=False,  # isolate the stitch failure first
    auto_normalize=True,
)
composer = VideoComposer()
try:
    result = composer.compose(clips, config)  # try 5 first for speed
    print("SUCCESS:", result)
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:2000])
    # dig into the chained cause
    tb = traceback.format_exc()
    print(tb[-2000:])
