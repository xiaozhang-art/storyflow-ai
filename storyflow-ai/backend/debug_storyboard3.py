"""Test raw DeepSeek call (no langchain) for storyboard prompt."""
import asyncio
import json
import sqlite3
import sys

sys.path.insert(0, ".")
import httpx
from configs.settings import settings
from prompts import STORYBOARD_SYSTEM_PROMPT, STORYBOARD_USER_PROMPT
from agents.storyboard_agent import _build_character_descriptions


async def main():
    conn = sqlite3.connect("storyflow.db")
    c = conn.cursor()
    c.execute("SELECT episode_no, title, summary, script FROM episode ORDER BY episode_no LIMIT 1")
    r = c.fetchone()
    ep = {"episode_no": r[0], "title": r[1], "summary": r[2], "script": r[3]}
    c.execute("SELECT name, appearance FROM character")
    chars = [{"name": x[0], "appearance": json.loads(x[1]) if x[1] else {}} for x in c.fetchall()]
    conn.close()

    char_desc = _build_character_descriptions(chars)
    user_prompt = STORYBOARD_USER_PROMPT.format(
        episode_no=ep["episode_no"], title=ep["title"],
        summary=ep["summary"], script=ep["script"],
        character_descriptions=char_desc,
        min_scenes=5, max_scenes=10, format_instructions="",
    )

    for i in range(2):  # two consecutive calls like the real flow
        r = httpx.post(
            settings.LLM_BASE_URL + "/chat/completions",
            headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            json={
                "model": settings.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": STORYBOARD_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 4096,
                "temperature": 0.4,
            },
            timeout=120,
        )
        body = r.json()
        content = body["choices"][0]["message"]["content"] if body.get("choices") else None
        fin = body.get("choices", [{}])[0].get("finish_reason")
        print(f"call {i+1}: HTTP {r.status_code} | finish={fin} | content len={len(content or '')} | usage={body.get('usage')}")
        if content:
            print("  first 120:", repr(content[:120]))
        else:
            print("  raw body:", str(body)[:300])


asyncio.run(main())
