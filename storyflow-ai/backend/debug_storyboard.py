"""Debug storyboard generation with real data from DB."""
import asyncio
import json
import sqlite3
import logging
import sys

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

sys.path.insert(0, ".")
from configs.settings import settings
from app.llm import get_precise_llm
from agents.storyboard_agent import _generate_storyboard_for_episode, _build_character_descriptions


async def main():
    conn = sqlite3.connect("storyflow.db")
    c = conn.cursor()
    c.execute("SELECT episode_no, title, summary, script FROM episode ORDER BY episode_no")
    eps = [{"episode_no": r[0], "title": r[1], "summary": r[2], "script": r[3]} for r in c.fetchall()]
    c.execute("SELECT name, appearance FROM character")
    chars = [{"name": r[0], "appearance": json.loads(r[1]) if r[1] else {}} for r in c.fetchall()]
    conn.close()

    print(f"episodes: {len(eps)}, characters: {len(chars)}")
    char_desc = _build_character_descriptions(chars)
    print("char_desc:", char_desc[:200])

    llm = get_precise_llm()
    scenes = await _generate_storyboard_for_episode(eps[0], char_desc, llm)
    print(f"\n==> episode 1 produced {len(scenes)} scenes")
    for s in scenes[:3]:
        print(json.dumps(s, ensure_ascii=False)[:300])


asyncio.run(main())
