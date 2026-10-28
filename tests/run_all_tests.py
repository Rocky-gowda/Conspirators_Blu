"""End-to-end test run with a FAKE local AI (no real model needed, safe to run beside the real app).

    py -3.11 tests/run_all_tests.py

Starts the fake Ollama on port 11500 and a test copy of the app on port 8100 (silent voice, a separate
data folder), runs every scenario, prints PASS/FAIL, and stops both. Exit code 1 if anything failed.
"""
import json
import re
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
APP, FAKE = "http://127.0.0.1:8100", "http://127.0.0.1:11500"
results = []
NET_LOG = ROOT / "data_test_net.log"


def start(env_extra, fake_mode="ok"):
    env = dict(os.environ, BLU_TTS="silent", OLLAMA_URL=FAKE, BLU_SERVER=APP, BLU_DATA=str(ROOT / "data_test"),
               FAKE_MODE=fake_mode, FAKE_TPS="200", BLU_STALL_S="8", PYTHONUNBUFFERED="1")
    # Wi-Fi off: no proxy, and every non-local connection is refused and logged (tests/offline_guard)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(k, None)
    env["PYTHONPATH"] = str(ROOT / "tests" / "offline_guard")
    env["BLU_NET_LOG"] = str(NET_LOG)
    env.update(env_extra)
    for k in [k for k, v in env.items() if v == ""]:
        del env[k]                          # "" means: leave this setting unset
    procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "tests.fake_ollama:app", "--port", "11500"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
             subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app", "--port", "8100"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    for _ in range(80):
        try:
            requests.get(APP + "/api/languages", timeout=1)
            requests.get(FAKE + "/api/tags", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    return procs


def stop(procs):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(10)
        except Exception:
            p.kill()


class Skip(Exception):
    pass


def check(name, fn):
    t0 = time.time()
    try:
        detail = fn() or ""
        results.append(("PASS", name, f"{time.time() - t0:.1f}s", detail))
    except Skip as e:
        results.append(("SKIP", name, f"{time.time() - t0:.1f}s", str(e)))
    except Exception as e:
        results.append(("FAIL", name, f"{time.time() - t0:.1f}s", f"{type(e).__name__}: {e}"))


def job(url, body, timeout=240, wait_mp4=True):
    j = requests.post(APP + url, json=body).json()
    t0 = time.time()
    while j.get("status") not in ("done", "error"):
        if time.time() - t0 > timeout:
            raise TimeoutError("job did not finish")
        time.sleep(0.4)
        j = requests.get(f"{APP}/api/jobs/{j['id']}").json()
    j["done_after"] = round(time.time() - t0, 2)          # when the learner can go on (MP4 may still record)
    while wait_mp4 and j.get("status") == "done" and j.get("mp4_state") == "rendering":
        if time.time() - t0 > timeout:
            raise TimeoutError("MP4 did not finish")
        time.sleep(0.4)
        j = dict(requests.get(f"{APP}/api/jobs/{j['id']}").json(), done_after=j["done_after"])
    return j


def lesson(topic, level="beginner", seconds=45, **kw):
    return job("/api/generate", {"topic": topic, "level": level, "seconds": seconds, **kw})


def meta(lid):
    return requests.get(f"{APP}/api/lessons/{lid}/meta").json()


def main():
    shutil.rmtree(ROOT / "data_test", ignore_errors=True)
    NET_LOG.unlink(missing_ok=True)
    procs = start({})
    try:
        def t1():
            j = lesson("Photosynthesis")
            assert j["status"] == "done", j.get("error")
            m = meta(j["lesson_id"])
            assert m["kb"] == "photosynthesis" and m["mp4"]["ok"], m.get("mp4")
            return f"ready in {j['timings']['ready_to_play']}s, {m['duration']:.0f}s video, MP4 {m['mp4']['video']}"
        check("1 valid academic topic -> narrated, verified MP4", t1)

        def t2():
            j = lesson("Virat Kohli")
            assert j["status"] == "done", j.get("error")
            m = meta(j["lesson_id"])
            assert m["kb"] is None and m["domain"] == "person" and any(s["type"] == "timeline" for s in m["scenes"])
            return "person lesson, labelled not verified"
        check("2 named entity (Virat Kohli)", t2)

        def t3():
            r = requests.post(APP + "/api/generate", json={"topic": "Artificial Intelligence"})
            assert r.status_code == 409 and len(r.json()["detail"]["analysis"]["suggestions"]) >= 3
            return "asks the learner to pick a narrower topic"
        check("3 broad topic", t3)

        def t4():
            r = requests.post(APP + "/api/generate", json={"topic": "asdf qwer zxcv"})
            assert r.status_code == 400
            r = requests.post(APP + "/api/generate", json={"topic": "xkcd photosynthesis qwrtp"})
            assert r.status_code == 409 and r.json()["detail"]["analysis"]["suggestions"]
            return "refused / suggestion offered"
        check("4 irrelevant random string", t4)

        def t5():
            j = lesson("photosynthsis", seconds=30)
            assert j["status"] == "done" and any("understood as" in n for n in j["notes"])
            return "corrected to photosynthesis"
        check("5 misspelled topic", t5)

        def t6():
            j = lesson("The Mughal empire")           # the fake AI writes an off-topic Python lesson, twice
            assert j["status"] == "error" and "no checked offline lesson" in j["error"], j.get("error")
            assert any("off topic" in n for n in j["notes"])
            assert sum("retrying once with feedback" in n for n in j["notes"]) == 1     # bounded: one retry
            return "off-topic AI scenes rejected, one retry, honest message"
        check("6/14 insufficient knowledge + irrelevant content", t6)

        def s11():
            j = lesson("French Revolution")           # off topic first; correct after the feedback retry
            assert j["status"] == "done", j.get("error")
            assert any("retrying once with feedback" in n for n in j["notes"])
            m = meta(j["lesson_id"])
            assert "French" in m["title"], m["title"]
            return "1st answer rejected (off topic), retry with reasons succeeded"
        check("S11 irrelevant output -> bounded retry with feedback", s11)

        def s2():
            r = requests.post(APP + "/api/generate", json={"topic": "phito systhse"})
            assert r.status_code == 409, r.status_code
            sugg = r.json()["detail"]["analysis"]["suggestions"]
            assert sugg == ["photosynthesis"], sugg
            j = lesson(sugg[0], seconds=30)
            assert j["status"] == "done" and meta(j["lesson_id"])["kb"] == "photosynthesis"
            return "asked 'Did you mean photosynthesis?' -> photosynthesis lesson"
        check("S2 misspelled 'phito systhse'", s2)

        def s6():
            heads = {}
            for lv in ("beginner", "intermediate", "advanced"):
                j = lesson("python works", level=lv, seconds=60)
                assert j["status"] == "done", j.get("error")
                m = meta(j["lesson_id"])
                assert m["kb"] == "python_basics" and any(s["type"] == "code_walkthrough" for s in m["scenes"])
                heads[lv] = tuple(s["heading"] for s in m["scenes"][1:])
            assert len(set(heads.values())) == 3, heads
            return "3 different lessons: " + " | ".join(h[1][:22] for h in heads.values())
        check("S6 Python at beginner / intermediate / advanced", s6)

        def s18():
            j = lesson("difference between acids and bases", level="intermediate", seconds=60)
            assert j["status"] == "done", j.get("error")
            m = meta(j["lesson_id"])
            assert any(s["type"] == "table" for s in m["scenes"]), [s["type"] for s in m["scenes"]]
            return "comparison topic -> table scene, rows appear with the voice"
        check("S18 comparison topic gets a table", s18)

        def s7():
            j = lesson("photosynthesis", seconds=60)
            m = meta(j["lesson_id"])
            assert any(s["type"] == "illustration" for s in m["scenes"]), [s["type"] for s in m["scenes"]]
            return "illustration scene: plant, sun, water, CO2 in; glucose, O2 out"
        check("S7 photosynthesis with topic picture", s7)

        def s8_9():
            out = []
            for secs, topic in ((30, "Newton's laws of motion"), (60, "How does the human heart work?")):
                j = lesson(topic, level="intermediate", seconds=secs)
                assert j["status"] == "done", j.get("error")
                m = meta(j["lesson_id"])
                bad = {k: v for k, v in m["checks"].items() if not v["ok"]}
                assert not bad, bad
                assert m["mp4"]["ok"] and abs(m["mp4"]["duration"] - m["duration"]) < 0.5
                out.append(f"{secs}s -> {m['duration']:.1f}s, {sum(s['type'] != 'title_card' for s in m['scenes'])} scenes")
            return "; ".join(out)
        check("S8/S9 30 s and 60 s: length within ±15 %, 3+ scenes, MP4 checked", s8_9)

        def s10():
            j = lesson("Photosynthesis", seconds=30, language="hi")
            if j["status"] == "error" and re.search(r"(?i)translat|torch|indictrans", j["error"]):
                raise Skip("translation model not installed in this test machine: " + j["error"][:60])
            assert j["status"] == "done", j.get("error")
            return "Hindi lesson built"
        check("S10 translation + narration (Hindi)", s10)

        def s14():
            j = lesson("Photosynthesis", seconds=30)
            lid = j["lesson_id"]
            raw = requests.get(f"{APP}/lessons/{lid}/lesson.mp4").content
            assert raw.find(b"moov") < raw.find(b"mdat"), "moov atom must come first (fast start)"
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.launch()
                pg = b.new_page()
                pg.goto(f"{APP}/player.html?id={lid}")       # same origin as the file
                res = pg.evaluate("""async (src) => {
                    const v = document.createElement('video'); v.muted = true; v.src = src; document.body.appendChild(v);
                    await v.play(); await new Promise(r => setTimeout(r, 2500));
                    return {t: v.currentTime, err: v.error && v.error.code, w: v.videoWidth, h: v.videoHeight,
                            dropped: v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality().droppedVideoFrames : -1};
                }""", f"/lessons/{lid}/lesson.mp4")
                b.close()
            assert res["err"] is None and res["t"] > 1.5 and (res["w"], res["h"]) == (1280, 720), res
            return f"played {res['t']:.1f}s in Chromium, {res['w']}x{res['h']}, dropped frames {res['dropped']}, fast start"
        check("S14 exported MP4 plays in a browser", s14)

        def t7():
            data = (ROOT / "samples" / "Science_notes_plants_and_water.pdf").read_bytes()
            d = requests.post(APP + "/api/exam/upload?name=notes.pdf", data=data).json()
            j = job("/api/exam/create", {"doc_id": d["id"], "count": 6, "types": ["mcq", "tf"]})
            assert j["status"] == "done", j.get("error")
            e = requests.get(f"{APP}/api/exam/{j['lesson_id']}").json()
            assert len(e["questions"]) == 6 and "answer" not in e["questions"][0]
            assert any("not supported by the PDF" in n for n in j["notes"])
            r = requests.post(f"{APP}/api/exam/{e['id']}/submit", json={"answers": {"0": 0}}).json()
            assert r["total"] == 6 and r["sections"]
            return f"{len(e['questions'])} grounded questions, unsupported ones dropped, graded {r['percent']}%"
        check("7 exam from a relevant PDF", t7)

        def t8():
            r = requests.post(APP + "/api/exam/upload?name=x.pdf", data=b"%PDF-1.4 tiny")
            assert r.status_code == 400
            return r.json()["detail"][:60]
        check("8 PDF without enough information", t8)

        def t13():
            h = requests.get(APP + "/api/history").json()
            n = len(h)
            assert requests.delete(f"{APP}/api/lessons/{h[0]['id']}").status_code == 200
            assert len(requests.get(APP + "/api/history").json()) == n - 1
            assert requests.delete(f"{APP}/api/lessons/..%2Fetc").status_code in (400, 404, 405)
            return f"{n} -> {n - 1} lessons, path tricks refused"
        check("13 history item deletion", t13)

        def t_revoice():
            j = lesson("How does a Python loop work?", seconds=30)
            r = job(f"/api/lessons/{j['lesson_id']}/revoice", {"language": "en", "gender": "male", "speed": 1.1})
            assert r["status"] == "done" and "plan" not in r["timings"]
            return "no AI call needed"
        check("revoice without re-planning", t_revoice)

        def t_len():
            j = lesson("Explain Ohm's law", level="advanced", seconds=60)
            d = meta(j["lesson_id"])["duration"]
            assert 48 <= d <= 69, d
            return f"60 s requested -> {d:.1f} s"
        check("length matches the choice", t_len)
    finally:
        stop(procs)

    procs = start({"BLU_KB_FIRST": "0"}, fake_mode="stall")      # force the AI path for this checked topic
    try:
        def t_stall():
            j = lesson("Pythagorean theorem", level="advanced", seconds=60)
            assert j["status"] == "done", j.get("error")
            return "model stopped mid-lesson; finished from checked notes"
        check("model stops part-way", t_stall)
    finally:
        stop(procs)

    procs = start({}, fake_mode="lazy")
    try:
        def s17():
            j = lesson("Virat Kohli", seconds=45, force=True)          # force: really ask the (lazy) AI
            assert j["status"] == "done", j.get("error")
            m = meta(j["lesson_id"])
            assert sum(s["type"] != "title_card" for s in m["scenes"]) >= 3, m["scenes"]
            assert any("planned by" in n for n in j["notes"]), j["notes"]
            return "AI left out labels: scenes made from its sentences, lesson complete"
        check("S17 lazy AI answer (headings and sentences only)", s17)
    finally:
        stop(procs)

    procs = start({"FAKE_TPS": "40"})            # a slow AI (about as fast as phi4-mini on a laptop CPU)
    try:
        def s16():
            j = lesson("Virat Kohli", seconds=60)          # no checked notes: the AI path
            assert j["status"] == "done", j.get("error")
            t = j["timings"]
            assert t["ready_to_play"] < t["plan"], t           # playback started before the AI finished
            assert "first_teaching_slide" in t and t["first_teaching_slide"] < t["plan"] + 2, t
            assert t["ready_to_play"] <= 4.0, t
            k = lesson("Explain Ohm's law", seconds=60)         # checked notes: instant
            assert k["status"] == "done" and k["timings"]["ready_to_play"] <= 3.0, k["timings"]
            assert any("checked offline lesson" in n for n in k["notes"])
            assert k["done_after"] <= 5.0, k["done_after"]    # finished without waiting for the MP4
            return (f"new topic: playing after {t['ready_to_play']:.1f}s, done after {j['done_after']:.0f}s "
                    f"(AI wrote for {t['plan']:.0f}s); checked topic: playing after {k['timings']['ready_to_play']:.1f}s, "
                    f"done after {k['done_after']:.1f}s, MP4 {k['timings'].get('export_mp4', 0):.0f}s in the background")
        check("S16 instant start (slow AI)", s16)
    finally:
        stop(procs)

    procs = start({})
    for p in procs[:1]:
        p.terminate()                      # no Ollama at all
    try:
        def t10():
            j = lesson("how plants make food")
            assert j["status"] == "done", j.get("error")
            assert meta(j["lesson_id"])["kb"] == "photosynthesis"
            j = lesson("Virat Kohli")
            assert j["status"] == "error" and "Ollama is not running" in j["error"]
            return "matching offline lesson / clear message"
        check("10 Ollama unavailable", t10)
    finally:
        stop(procs)

    procs = start({"BLU_TTS": "", "BLU_MODELS": str(ROOT / "data_test" / "no_models")})
    try:
        def t11():
            j = lesson("Binary search", seconds=30)
            assert j["status"] == "error" and "Voice" in j["error"], j.get("error")
            return j["error"][:70]
        check("11 narration failure (voice files missing)", t11)
    finally:
        stop(procs)
    shutil.rmtree(ROOT / "data_test", ignore_errors=True)

    def s13():
        log = NET_LOG.read_text(encoding="utf-8") if NET_LOG.exists() else ""
        assert not log.strip(), log[:300]
        return "no connection outside this computer was attempted during all the tests above"
    check("S13 offline: network blocked for the whole run", s13)
    NET_LOG.unlink(missing_ok=True)

    w = max(len(r[1]) for r in results)
    print()
    for st, name, t, d in results:
        print(f"{st}  {name:<{w}}  {t:>6}  {d}")
    failed = sum(r[0] == "FAIL" for r in results)
    skipped = sum(r[0] == "SKIP" for r in results)
    print(f"\n{len(results) - failed - skipped}/{len(results)} passed, {skipped} skipped, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
