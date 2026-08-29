"""End-to-end test: create story -> start generation -> poll -> fetch result."""
import json
import sys
import time

import httpx

BASE = "http://localhost:8000"
client = httpx.Client(timeout=120)

# 1. Create story (proper UTF-8)
r = client.post(f"{BASE}/api/story", json={
    "title": "雨夜奇遇",
    "prompt": "一个失意的少年程序员在雨夜捡到一只会说话的猫，这只猫自称是异世界的守护者，两人从此结伴展开奇幻冒险",
    "genre": "奇幻",
})
print("create:", r.status_code)
story = r.json()
story_id = story["id"]
print("story_id:", story_id, "| title:", story["title"])

# 2. Start generation
r = client.post(f"{BASE}/api/story/{story_id}/generate")
print("generate:", r.status_code, r.text[:200])
task_id = r.json().get("task_id", "")

# 3. Poll task status
start = time.time()
last_step = ""
while time.time() - start < 900:  # up to 15 min
    r = client.get(f"{BASE}/api/task/{task_id}")
    data = r.json()
    status = data.get("status")
    step = data.get("current_step", "")
    progress = data.get("progress")
    err = data.get("error_message", "")
    if (status, step) != last_step:
        last_step = (status, step)
        print(f"[{time.time()-start:6.1f}s] status={status} step={step} progress={progress}% {err}")
    if status in ("completed", "failed"):
        break
    time.sleep(5)

# 4. Fetch result
r = client.get(f"{BASE}/api/story/{story_id}/result")
print("\nresult:", r.status_code)
if r.status_code == 200:
    res = r.json()
    print(json.dumps(res, ensure_ascii=False, indent=2)[:2000])
else:
    print(r.text[:500])

# 5. Story status
r = client.get(f"{BASE}/api/story/{story_id}")
print("\nstory:", r.json().get("status"))
