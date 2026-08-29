"""Debug strategy-2 fallback: raw LLM call + parse."""
import asyncio
import json
import sqlite3
import sys

sys.path.insert(0, ".")
from langchain_core.prompts import ChatPromptTemplate
from prompts import STORYBOARD_SYSTEM_PROMPT, STORYBOARD_USER_PROMPT
from app.llm import get_precise_llm
from utils.json_helper import parse_json_response
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
    llm = get_precise_llm()

    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", STORYBOARD_SYSTEM_PROMPT),
        ("human", STORYBOARD_USER_PROMPT),
    ])
    chain = chat_prompt | llm
    response = await chain.ainvoke({
        "episode_no": ep["episode_no"], "title": ep["title"],
        "summary": ep["summary"], "script": ep["script"],
        "character_descriptions": char_desc,
        "min_scenes": 5, "max_scenes": 10,
        "format_instructions": "",
    })
    content = response.content
    print("=== raw response type:", type(content))
    print("=== first 300 chars:", repr(str(content)[:300]))
    print("=== last 200 chars:", repr(str(content)[-200:]))
    parsed = parse_json_response(str(content).strip())
    print("=== parse result type:", type(parsed))
    if isinstance(parsed, list):
        print("=== list len:", len(parsed))
        if parsed:
            print("=== first item keys:", list(parsed[0].keys()) if isinstance(parsed[0], dict) else "not dict")
    elif isinstance(parsed, dict):
        print("=== dict keys:", list(parsed.keys()))
        if "scenes" in parsed:
            print("=== scenes len:", len(parsed["scenes"]))


asyncio.run(main())
