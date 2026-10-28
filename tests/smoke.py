"""End-to-end smoke test: starts the server, generates a lesson through the API, checks the MP4.
    python tests/smoke.py [language] [topic]
Run it with Wi-Fi OFF before the demo.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:8000"
lang = sys.argv[1] if len(sys.argv) > 1 else "en"
topic = sys.argv[2] if len(sys.argv) > 2 else "How does a Python loop work?"

srv = None
try:
    requests.get(URL, timeout=1)
except Exception:
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app", "--port", "8000"], cwd=ROOT)
    for _ in range(40):
        try:
            requests.get(URL, timeout=1); break
        except Exception:
            time.sleep(0.5)
try:
    t0 = time.time()
    job = requests.post(f"{URL}/api/generate", json={"topic": topic, "language": lang, "seconds": 45}).json()
    while job["status"] not in ("done", "error"):
        time.sleep(1)
        job = requests.get(f"{URL}/api/jobs/{job['id']}").json()
    print(json.dumps(job, indent=1, ensure_ascii=False))
    print(f"total {time.time() - t0:.1f}s")
    if job["status"] == "done":
        mp4 = ROOT / "data" / "lessons" / job["lesson_id"] / "lesson.mp4"
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height",
                                "-of", "compact", str(mp4)], capture_output=True, text=True).stdout
        print(probe)
        print("MP4:", mp4)
finally:
    if srv:
        srv.terminate()
