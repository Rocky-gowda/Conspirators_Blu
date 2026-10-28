"""Generate lessons through the API and report streaming latency and length accuracy.
    python tests/stream_test.py "topic" level seconds [language]
"""
import json
import sys
import time

import requests

URL = "http://127.0.0.1:8000"
topic, level, secs = sys.argv[1], sys.argv[2], int(sys.argv[3])
lang = sys.argv[4] if len(sys.argv) > 4 else "en"
t0 = time.time()
job = requests.post(f"{URL}/api/generate", json={"topic": topic, "level": level, "seconds": secs, "language": lang}).json()
seen_playable, scene_counts = None, []
while job["status"] not in ("done", "error"):
    time.sleep(0.5)
    job = requests.get(f"{URL}/api/jobs/{job['id']}").json()
    if job["lesson_id"] and seen_playable is None:
        seen_playable = time.time() - t0
    if job["lesson_id"]:
        tl = requests.get(f"{URL}/lessons/{job['lesson_id']}/timeline.json").json()
        scene_counts.append((round(time.time() - t0, 1), len(tl["scenes"]), tl["complete"]))
total = time.time() - t0
print("status:", job["status"], job.get("error") or "")
print("timings:", job["timings"])
print("notes:", job["notes"])
if job["lesson_id"]:
    tl = requests.get(f"{URL}/lessons/{job['lesson_id']}/timeline.json").json()
    m = requests.get(f"{URL}/api/lessons/{job['lesson_id']}/meta").json()
    print(f"playable after {seen_playable:.1f}s, finished after {total:.1f}s")
    print(f"target {secs}s -> duration {tl['duration']:.1f}s ({100 * tl['duration'] / secs:.0f}%)")
    print("scenes:", [(s["type"], s["data"]["heading"]) for s in tl["scenes"]])
    print("growth (t, scenes, complete):", sorted(set(scene_counts))[:3], "...", scene_counts[-1:])
    print("domain:", m["domain"], "| kb:", m["kb"], "| next:", m["next_topics"], "| source:", m["source"])
