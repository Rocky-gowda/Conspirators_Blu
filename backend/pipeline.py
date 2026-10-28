"""Orchestrates the five stages, with streaming, caching, fallbacks, history and stage timings.

  understand (topic_nlp) -> plan (LLM, streamed scene by scene) -> translate -> voice -> play -> MP4

While the LLM streams, a worker thread translates and voices each finished scene, so the learner can
start watching after the first two scenes instead of waiting for the whole plan.
"""
import hashlib
import json
import logging
import queue
import re
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime

from . import config, exporter, knowledge, memory as mem, planner, retrieval, timeline, topic_nlp, translate, visual_plan
from .schema import Lesson, TitleCard, lesson_shape

log = logging.getLogger("pipeline")
JOBS: dict = {}
_run_lock = threading.Lock()  # one heavy job at a time: keeps RAM under control on 8 GB laptops


def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts + (config.VERSION,)).encode()).hexdigest()[:12]


def lesson_dir(lesson_id):
    return config.LESSONS_DIR / lesson_id


class Job:
    def __init__(self, kind, params):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.params = kind, params
        self.status, self.stage, self.progress, self.detail = "queued", "", 0.0, ""
        self.timings, self.notes = {}, []
        self.lesson_id = None
        self.error = None
        self.mp4 = False
        self.info = None
        self.memory = {}
        self.visual = None
        self.mp4_state = None          # None | rendering | ready | failed: ...
        self.t0 = time.perf_counter()
        JOBS[self.id] = self

    def to_dict(self):
        return {"id": self.id, "status": self.status, "stage": self.stage, "progress": round(self.progress, 2),
                "detail": self.detail, "timings": self.timings, "memory": self.memory, "notes": self.notes, "lesson_id": self.lesson_id,
                "error": self.error, "mp4": self.mp4, "mp4_state": self.mp4_state, "info": self.info,
                "visual": self.visual}

    def timed(self, name, fn, *a, **k):
        self.stage = name
        self.progress = 0
        t0 = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            self.timings[name] = round(self.timings.get(name, 0) + time.perf_counter() - t0, 2)

    def add_time(self, name, secs):
        self.timings[name] = round(self.timings.get(name, 0) + secs, 2)

    def playable(self, lid):
        if self.lesson_id != lid:
            self.lesson_id = lid
            self.status = "playable"
            self.timings["ready_to_play"] = round(time.perf_counter() - self.t0, 2)  # the wait the learner feels


# ------------------------------------------------------------------ shared building blocks

DOMAIN_ART = {"programming": ["code", "computer"], "history": ["book", "flag"], "person": ["person", "star"],
              "physics": ["atom", "ball"], "chemistry": ["flask", "atom"], "biology": ["cell", "dna"],
              "earth": ["earth", "cloud"], "math": ["book"], "general": ["book", "star"]}


def _title_card(title, topic, art=None, subtitle=None):
    t = (title or topic).strip()
    return TitleCard(type="title_card", heading=t[:90], subtitle=subtitle, art=art or None,
                     narration=[{"text": f"Let us learn about {t.rstrip('?.! ').lower()}."[:300]}])


def _title_art(info):
    """The drawings that open this lesson: from the visual plan (topic words), else the subject's."""
    arts = list((info.get("visual") or {}).get("arts") or [])
    return (arts or DOMAIN_ART.get(info.get("domain"), DOMAIN_ART["general"]))[:3]


def _finish(job, builder, en_scenes, loc_scenes, p, info, source, extra):
    """Write the finished lesson, its history record, and render the MP4."""
    d = builder.dir
    lid = d.name
    lang = p["language"]
    kb = knowledge.get(info.get("kb")) if info else None
    pre = extra.get("prerequisites") or (kb or {}).get("prerequisites", [])
    nxt = extra.get("next_topics") or (kb or {}).get("next_topics", [])
    title_en = extra.get("title") or info["topic"]
    common = {"level": p["level"], "domain": info["domain"], "prerequisites": pre[:4], "next_topics": nxt[:4]}
    en = Lesson(title=title_en[:90], language="en", scenes=en_scenes, **common)
    loc = Lesson(title=builder.meta.get("title", title_en)[:90], language=lang, scenes=loc_scenes, **common)
    (d / "lesson.en.json").write_text(en.model_dump_json(indent=2), encoding="utf-8")
    (d / f"lesson.{lang}.json").write_text(loc.model_dump_json(indent=2), encoding="utf-8")
    tl = builder.finalize(prerequisites=pre[:4], next_topics=nxt[:4])
    job.playable(lid)
    meta = {
        "id": lid, "topic": info["topic"], "original": info.get("original", info["topic"]), "fixes": info.get("fixes", []),
        "title": tl["title"], "level": p["level"], "language": lang, "domain": info["domain"],
        "target_seconds": p.get("seconds"), "duration": tl["duration"], "source": source,
        "model": extra.get("model"), "kb": info.get("kb"), "key_terms": info.get("key_terms", []),
        "facts_used": info.get("facts", []), "prerequisites": pre[:4], "next_topics": nxt[:4],
        "voice": {"gender": p.get("gender", "female"), "speed": p.get("speed", 1.0)},
        "scenes": [{"type": s["type"], "heading": s["data"]["heading"], "start": s["start"], "end": s["end"]}
                   for s in tl["scenes"]],
        "created": datetime.now().astimezone().isoformat(timespec="seconds"), "timings": job.timings, "notes": job.notes,
        "visual_plan": job.visual,
    }
    meta["checks"] = output_checks(tl, p.get("seconds"))
    for k, v in meta["checks"].items():
        if isinstance(v, dict) and not v["ok"]:
            job.notes.append(f"check '{k}' not met: {v['detail']}")
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    meta["memory"] = mem.snapshot(job)
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if p.get("export", True):
        # the lesson is finished and playing; the MP4 file is recorded in the background
        export_async(job, lid, d, tl["duration"], meta)


_export_lock = threading.Lock()


def export_async(job, lid, d, duration, meta=None):
    """Record the MP4 after the lesson is ready (the learner does not wait for it)."""
    job.mp4_state = "rendering"

    def run():
        try:
            with _export_lock:                      # one recording at a time
                t0 = time.perf_counter()
                exporter.export(lid, d)
                info = exporter.verify(d / "lesson.mp4", duration)      # raises if the file is broken
                job.timings["export_mp4"] = round(time.perf_counter() - t0, 2)
                m = meta if meta is not None else json.loads((d / "meta.json").read_text(encoding="utf-8"))
                m["mp4"] = info
                m["timings"] = job.timings
                (d / "meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
                job.mp4, job.mp4_state = True, "ready"
        except Exception as e:
            log.error("MP4 export failed: %s", traceback.format_exc())
            job.mp4_state = f"failed: {type(e).__name__}: {str(e)[:120]}"
    threading.Thread(target=run, daemon=True).start()


DURATION_TOLERANCE = 0.15     # the whole video must be within ±15 % of the chosen length,
DURATION_SLACK_S = 6.0        # or within 6 s for short lessons (3 real scenes need ~30-36 s of speech)


def output_checks(tl, target):
    """Final validation of a finished lesson: length, number of scenes, no empty scene."""
    scenes = tl["scenes"]
    teach = [s for s in scenes if s["type"] != "title_card"
             and (s.get("data") or {}).get("heading") != visual_plan.AGENDA_HEADING]
    out = {"scenes": {"ok": len(teach) >= 3, "detail": f"{len(teach)} scenes after the title card (need 3+)"},
           "no_empty_scene": {"ok": all(s["end"] - s["start"] >= 2.0 for s in scenes),
                              "detail": "every scene lasts at least 2 s"}}
    if target:
        dev = (tl["duration"] - target) / target
        allowed = max(DURATION_TOLERANCE * target, DURATION_SLACK_S)
        out["duration"] = {"ok": abs(tl["duration"] - target) <= allowed,
                           "detail": f"{tl['duration']:.1f} s for {target} s ({dev * 100:+.0f} %, allowed ±{allowed:.0f} s)"}
    return out


def _fresh_dir(lid):
    d = lesson_dir(lid)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_full(job, en: Lesson, lid, p, info, source, extra=None, loc: Lesson = None, add_recap=True, fit=True):
    """Build a lesson whose scenes are all known (checked lesson, cache, fallback, revoice, edit, prebake).

    Scene by scene: translate one scene, voice it, add it; playback starts after the first two scenes,
    so the learner never waits for the whole lesson. Pauses are paced per scene to land on the length."""
    extra = dict(extra or {})
    lang = p["language"]
    en_s = list(en.scenes)
    given = list(loc.scenes) if loc is not None else None
    d = _fresh_dir(lid)
    meta = {"id": lid, "title": loc.title if loc is not None else en.title, "level": p["level"], "language": lang,
            "domain": info["domain"], "target": p.get("seconds")}
    if loc is None and lang != "en":
        meta["title"] = translate.translate_texts([en.title], lang)[0]
    target = p.get("seconds") or 0
    if add_recap and target and given is None and not any(s.heading == "Recap" for s in en_s):
        # cheap text estimate (2.6 words/s): add a recap before the quiz if the lesson would be short
        words = sum(len(b.text.split()) for s in en_s for b in s.narration)
        if words / 2.6 + 1.8 * len(en_s) < target * 0.85:
            recap = planner.make_recap(en_s)
            if recap:
                en_s.insert(len(en_s) - 1 if en_s[-1].type == "quiz" else len(en_s), recap)
    builder = timeline.Builder(d, meta, p["gender"], p["speed"])
    loc_s = []
    t_voice = 0.0
    for i, s in enumerate(en_s):
        if given is not None:
            ls = given[i]
        else:
            t1 = time.perf_counter()
            ls = translate.translate_scene(s, lang)
            job.add_time("translate", time.perf_counter() - t1)
        loc_s.append(ls)
        t1 = time.perf_counter()
        gaps = {}
        if fit and target and s.type != "title_card":
            share = (target - builder.duration) / max(1, len(en_s) - i)
            gaps = timeline.paced_gaps(builder, ls, share)
        builder.add(ls, **gaps)
        t_voice += time.perf_counter() - t1
        if s.type != "title_card" and "first_teaching_slide" not in job.timings:
            job.timings["first_teaching_slide"] = round(time.perf_counter() - job.t0, 2)
        job.detail = f"voiced scene {i + 1} of {len(en_s)}"
        job.progress = (i + 1) / len(en_s)
        if i == 1 or len(en_s) == 1:
            job.playable(lid)
    job.add_time("voice", t_voice)
    extra.setdefault("title", en.title)
    extra.setdefault("prerequisites", en.prerequisites)
    extra.setdefault("next_topics", en.next_topics)
    _finish(job, builder, en_s, loc_s, p, info, source, extra)


# ------------------------------------------------------------------ the main flow

class PlanTooShort(Exception):
    pass


class NoFallback(Exception):
    pass


class _Fallback(Exception):
    """Go straight to the fallback, even though playback already started."""


class NoContent(Exception):
    """The AI produced no usable teaching scene (after its one retry); args[0] is the cause."""


def _stream_build(job, info, p, model, lid, seconds):
    """LLM streams scenes; a worker translates + voices each one; playable after two scenes."""
    lang = p["language"]
    d = _fresh_dir(lid)
    meta = {"id": lid, "title": info["topic"], "level": p["level"], "language": lang, "domain": info["domain"],
            "target": p["seconds"]}
    builder = timeline.Builder(d, meta, p["gender"], p["speed"])
    en_s, loc_s, errors, rejected = [], [], [], []
    q = queue.Queue()
    state = {"title": None}

    planned = lesson_shape(p["seconds"], p["level"])["scenes"]
    planned0 = planned                      # scenes the AI is asked for (title + teaching + quiz)
    ai_seconds = seconds

    def process(sc):
        t0 = time.perf_counter()
        loc = translate.translate_scene(sc, lang)
        t1 = time.perf_counter()
        gaps = {}
        if sc.type != "title_card" and en_s and len(en_s) < planned:
            # adaptive pacing: each teaching scene fills its fair share of the chosen length
            share = (p["seconds"] - builder.duration) / max(1, planned - len(en_s))
            gaps = timeline.paced_gaps(builder, loc, share)
        builder.add(loc, **gaps)
        job.add_time("translate", t1 - t0)
        job.add_time("voice", time.perf_counter() - t1)
        en_s.append(sc)
        loc_s.append(loc)
        job.detail = f"scene {len(en_s)} ready"
        if len(en_s) == 1 and "first_scene" not in job.timings:
            job.timings["first_scene"] = round(time.perf_counter() - job.t0, 2)
        if sc.type != "title_card" and "first_teaching_slide" not in job.timings:
            # the measure that matters: when the first slide that actually teaches is ready to play
            job.timings["first_teaching_slide"] = round(time.perf_counter() - job.t0, 2)
        if len(en_s) >= 2:
            job.playable(lid)

    topic_words = set(retrieval.tokens(info["topic"] + " " + " ".join(e["text"] for e in info.get("entities", []))))

    def title_ok():
        t = state["title"]
        return t if t and set(retrieval.tokens(t)) & topic_words else None

    context = set(retrieval.tokens(" ".join([info["topic"], " ".join(info.get("key_terms", [])),
                                             " ".join(e["text"] for e in info.get("entities", [])),
                                             " ".join(info.get("facts", []))])))

    def worker():
        while True:
            sc = q.get()
            if sc is None:
                q.task_done()
                return
            try:
                if sc.type == "title_card":
                    if en_s:
                        continue                    # only one title card
                    if not set(retrieval.tokens(_scene_text(sc))) & topic_words:
                        job.notes.append("the model's title was off topic; using the learner's topic")
                        sc = _title_card(None, info["topic"])
                elif not en_s:
                    process(_title_card(title_ok(), info["topic"]))
                ok, why = validate_scene(sc, context, en_s, lenient=bool(title_ok()), topic_kb=info.get("kb"))
                if not ok:
                    job.notes.append(f"scene '{sc.heading}' rejected: {why}")
                    rejected.append(f"scene '{sc.heading[:40]}' was {why}")
                    continue
                process(sc)
                context.update(retrieval.tokens(_scene_text(sc)))
            except Exception as e:                   # keep streaming; report at the end
                log.error(traceback.format_exc())
                errors.append(e)
            finally:
                if sc is not None:
                    q.task_done()

    def on_title(t):
        state["title"] = t
        if title_ok():
            builder.meta["title"] = translate.translate_texts([t], lang)[0]

    def on_progress(f):
        job.progress = f

    # instant start: Blu makes the title card and a "what we will learn" scene itself (no AI needed),
    # voices them and starts playback; the AI writes the rest while these play
    kb0 = knowledge.get(info.get("kb"))
    process(_title_card(kb0["lesson"]["title"] if kb0 else None, info["topic"], _title_art(info)))
    agenda = None              # (a generic "what we will learn" scene looked the same for every topic: removed)
    job.playable(lid)
    job.notes.append("playback started before the AI wrote anything (title card made instantly)")

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    res, stream_err = {"title": None, "prerequisites": [], "next_topics": [], "tokens": 0, "tps": 0}, None
    ask_info = info
    try:
        for attempt in (1, 2):
            try:
                res = job.timed("plan", planner.stream_plan, ask_info, p["level"], ai_seconds, model,
                                on_title, q.put, on_progress)
                job.notes.append(f"planned by {model}: {res['tokens']} tokens, {res['tps']} tokens/s")
                if res.get("dropped"):
                    job.notes.append(f"{res['dropped']} scene(s) from the AI could not be used (incomplete)")
            except Exception as e:          # the model failed part-way: keep what it wrote
                stream_err = e
                break
            q.join()                         # wait until every streamed scene has been checked
            got = [x for x in en_s if x.type != "title_card" and x is not agenda]
            if got or not rejected or attempt == 2:
                break
            # every scene was rejected: ONE retry that tells the model exactly what was wrong; the
            # lesson keeps playing (title + plan) while it writes again
            job.notes.append("retrying once with feedback: " + "; ".join(rejected[:3]))
            ask_info = dict(info, feedback=list(rejected))
    finally:
        q.put(None)
        th.join()
    info = ask_info if ask_info is not info else info
    if errors and not loc_s:
        raise errors[0]
    content = [s for s in en_s if s.type != "title_card" and s is not agenda]
    # smart validation: ask the model again for missing scenes, one at a time (max 2 calls)
    asks = 0
    while (content and len(content) < max(2, planned0 - 2) and asks < 2 and seconds == p["seconds"]
           and not isinstance(stream_err, ConnectionError)):
        asks += 1
        try:
            sc = planner.ask_scene(info, p["level"], seconds, model, [x.heading for x in en_s], len(content) + 1)
        except Exception as e:
            job.notes.append(f"re-asking the model failed ({type(e).__name__})")
            break
        ok, why = (False, "empty") if sc is None else validate_scene(sc, context, en_s)
        if ok:
            process(sc)
            context.update(retrieval.tokens(_scene_text(sc)))
            content.append(sc)
            job.notes.append(f"re-asked the model for one more scene: '{sc.heading}'")
        else:
            job.notes.append(f"re-asked scene rejected: {why}")
    if not content:
        raise NoContent(stream_err or PlanTooShort("no usable scenes from the model", rejected))
    if stream_err is not None:
        job.notes.append(f"model stopped early ({type(stream_err).__name__}); finishing from the knowledge base")
    elif len(content) < 2:
        job.notes.append("model wrote too little; finishing from the knowledge base")

    def append(sc, note=None, **kw):
        loc = translate.translate_scene(sc, lang)
        builder.add(loc, **kw)
        en_s.append(sc)
        loc_s.append(loc)
        if note:
            job.notes.append(note)

    # complete a short or interrupted lesson with checked scenes from the offline knowledge base
    kb = knowledge.get(info.get("kb"))
    kb_scenes = knowledge.assemble(kb["id"], p["level"], p["seconds"]).scenes if kb else []
    have_quiz = any(s.type == "quiz" for s in en_s)
    if kb_scenes and (stream_err is not None or len(content) < planned0 - 2 or builder.duration < p["seconds"] * 0.7):
        used = {s.heading.lower() for s in en_s}
        quiz_at = None
        for sc in kb_scenes[1:]:
            if builder.duration >= p["seconds"] * 0.8:
                break
            if sc.type == "quiz" or re.sub(r"^step \d+:\s*", "", sc.heading.lower()) in \
                    {re.sub(r"^step \d+:\s*", "", u) for u in used}:
                continue
            if have_quiz and quiz_at is None:
                quiz_at = True        # quiz already played; extra scenes still help
            append(sc, f"added '{sc.heading}' from the offline knowledge base")
    if not have_quiz:
        kq = [s for s in kb_scenes if s.type == "quiz"]
        if kq:
            append(kq[0], "quiz added from the offline knowledge base")
    else:
        # the quiz answer must have been taught; otherwise swap in a checked quiz when one exists
        qz = [s for s in en_s if s.type == "quiz"][-1]
        taught = set(retrieval.tokens(" ".join(_scene_text(s) for s in en_s if s.type != "quiz") + " " +
                                      " ".join(info.get("facts", []))))
        ans = set(retrieval.tokens(qz.options[qz.answer]))
        if ans and not ans & taught:
            job.notes.append("quiz answer was not taught in the lesson" +
                             ("; a checked quiz was added" if kb_scenes else ""))
            kq = [s for s in kb_scenes if s.type == "quiz"]
            if kq:
                append(kq[0])
    # length: add a recap (and a little pause) if the lesson came out short, or if it has
    # fewer than 3 scenes after the title card
    target = p["seconds"]
    if builder.duration < target * 0.85 or sum(s.type != "title_card" for s in en_s) < 3:
        recap = planner.make_recap(en_s)
        if recap:
            loc = translate.translate_scene(recap, lang)
            pad = min(8.0, max(0.0, target * 0.95 - builder.duration - builder.estimate(loc)))
            builder.add(loc, tail_pad=pad)
            en_s.append(recap)
            loc_s.append(loc)
            job.notes.append(f"recap scene added to reach the {target}s target")
    if sum(x.type != "title_card" for x in en_s) < 2:
        # not enough real content to make a lesson: say so honestly (no broken lesson, no unrelated one)
        raise NoContent(PlanTooShort("the AI wrote too few usable scenes", rejected))
    job.playable(lid)
    if info.get("visual"):
        vc = visual_plan.check(info["visual"], en_s)
        job.visual = dict(job.visual or {}, followed=vc["followed"], planned=vc["planned"])
        job.notes.append(f"visual plan followed in {vc['followed']} of {vc['planned']} scenes")
        job.notes.extend(vc["notes"])
    _finish(job, builder, en_s, loc_s, p, info, "ai",
            {"title": title_ok() or info["topic"], "prerequisites": res["prerequisites"],
             "next_topics": res["next_topics"], "model": model})
    return Lesson.model_validate_json((builder.dir / "lesson.en.json").read_text(encoding="utf-8"))


def _scene_text(sc) -> str:
    d = sc.model_dump()
    parts = [d.get("heading", ""), d.get("subtitle") or "", d.get("question", ""), d.get("problem", ""),
             d.get("answer", "") if isinstance(d.get("answer"), str) else "", d.get("chart_title") or "",
             d.get("code", "")]
    for k in ("items", "edge_labels", "options", "steps", "labels", "output"):
        parts += [str(x) for x in (d.get(k) or [])]
    parts += [e["label"] + " " + e["text"] for e in d.get("events") or []]
    parts += [(x.get("label") or "") + " " + (x.get("via") or "") for x in d.get("parts") or []]
    parts += [str(c) for c in d.get("columns") or []] + [str(c) for r in d.get("rows") or [] for c in r]
    parts += [b["text"] for b in d["narration"]]
    return " ".join(parts)


def validate_scene(sc, context: set, previous, lenient: bool = False, topic_kb=None) -> tuple:
    """Checks that repair cannot do: is the scene on topic, in English, and new?

    lenient (the AI's own title is on topic): different wording is fine ("France ... Bastille" in a French
    Revolution lesson); the scene is rejected only if it is clearly about ANOTHER known subject."""
    if sc.type == "title_card":
        return True, ""
    text = _scene_text(sc)
    letters = [c for c in text if c.isalpha()]
    if letters and sum(ord(c) > 127 for c in letters) / len(letters) > 0.3:
        return False, "not written in English (it is translated later)"
    words = set(retrieval.tokens(text))
    if context and not words & context:
        if not lenient:
            return False, "off topic (shares no key words with the topic or earlier scenes)"
        cores = retrieval._fields()
        other = max(((len(words & cores[tid][0]), tid) for tid in cores if tid != topic_kb), default=(0, None))
        if other[0] >= 2:                      # uses the core words of a different subject we know
            return False, f"off topic (it is about {knowledge.get(other[1])['lesson']['title']})"
    for p in previous:
        pw = set(retrieval.tokens(_scene_text(p)))
        if p.type == sc.type and pw and len(words & pw) / max(1, len(words | pw)) > 0.8:
            return False, f"repeats '{p.heading}'"
    return True, ""


FALLBACK_MIN_SCORE = 0.6       # an offline lesson replaces the AI lesson only for a strong topic match


def fallback_lesson_id(name, p):
    return "fallback_" + _key("fb", name, p["level"], p["seconds"], p["language"], p["gender"], p["speed"])


def _play_fallback(job, info, p, why):
    """The demo never breaks: play the closest ready-made lesson, built for this level and length."""
    name = info.get("kb")
    if name and (info.get("kb_score") or 0) < FALLBACK_MIN_SCORE:
        # weak match: fine as background for the AI, but not good enough to replace the lesson
        name = None
    if not name:
        # no checked lesson for this topic: say so honestly instead of showing an unrelated one
        offline = [kb["lesson"]["title"] for kb in knowledge.all_topics().values()]
        job.notes.append(f"technical reason: {why[:200]}")
        reason = "Ollama is not running" if "Ollama is not running" in why else "the AI's answer was not usable"
        raise NoFallback(f"The AI could not make this lesson ({reason}), and there is no checked offline lesson "
                         f"for “{info['topic']}”. Try again, choose a shorter length, or pick an offline topic: "
                         + ", ".join(offline[:6]) + ".")
    job.notes.append(f"offline lesson '{knowledge.get(name)['lesson']['title']}' used ({why[:160]})")
    if job.visual:
        job.visual["note"] = "the offline lesson uses its own checked pictures"
    lid = fallback_lesson_id(name, p)
    d = lesson_dir(lid)
    if (d / "timeline.json").exists() and json.loads((d / "timeline.json").read_text(encoding="utf-8")).get("complete"):
        job.playable(lid)
        job.mp4 = (d / "lesson.mp4").exists()
        if not job.mp4 and p.get("export", True):
            export_async(job, lid, d, json.loads((d / "timeline.json").read_text(encoding="utf-8"))["duration"])
        return
    kb_info = dict(info, kb=name, domain=knowledge.get(name)["domain"], facts=knowledge.get(name)["facts"])
    en = knowledge.assemble(name, p["level"], p["seconds"])
    build_full(job, en, lid, p, kb_info, "fallback")


def _measured(fn):
    """Run a job while sampling peak memory (app + browser + Ollama) for the speed report."""
    def run(job):
        mem.start(job)
        try:
            fn(job)
        finally:
            mem.stop(job)
    return run


def run_generate(job: Job):
    p = job.params
    model = p.get("model") or config.OLLAMA_MODEL
    info = None
    try:
        with _run_lock:
            job.status = "running"
            try:
                info = job.timed("understand", topic_nlp.analyze, p["topic"])
            except Exception as e:           # documented system-level fallback: basic cleaning only
                log.error("NLP stage failed: %s", traceback.format_exc())
                info = topic_nlp.basic(p["topic"])
                job.notes.append(f"topic analysis failed ({type(e).__name__}); using the topic as typed")
            job.info = info
            if info["status"] == "invalid":
                raise NoFallback(info["message"])
            if info["fixes"]:
                job.notes.append("understood as: " + info["topic"])
            # visual reasoning: choose the picture for each part of the lesson before the AI writes
            try:
                vp = job.timed("visual_plan", visual_plan.plan, info, p["level"], p["seconds"])
                info = dict(info, visual=vp)
                job.visual = {"summary": vp["summary"], "scenes": vp["scenes"][1:-1]}
                job.notes.append("visual plan: " + vp["summary"])
            except Exception:
                log.error("visual plan failed: %s", traceback.format_exc())
            job.notes.append("offline notes: " + (knowledge.get(info["kb"])["lesson"]["title"] if info["kb"]
                                                  else "none (AI general knowledge, not verified)"))
            if config.KB_FIRST and info.get("kb") and (info.get("kb_score") or 0) >= config.KB_FIRST_MIN_SCORE \
                    and not p.get("use_ai"):
                # strong match with the checked notes: play the checked lesson now (verified, no AI wait,
                # works even when Ollama is not running)
                kbx = knowledge.get(info["kb"])
                lid = _key("checked", info["kb"], p["level"], p["seconds"], p["language"], p["gender"], p["speed"])
                d = lesson_dir(lid)
                if not p.get("force") and (d / "meta.json").exists():
                    job.notes.append("checked lesson loaded from history (instant)")
                    job.playable(lid)
                    job.mp4 = (d / "lesson.mp4").exists()
                    if not job.mp4 and p.get("export", True):
                        export_async(job, lid, d, json.loads((d / "timeline.json").read_text(encoding="utf-8"))["duration"])
                    job.status = "done"
                    return
                job.notes.append(f"checked offline lesson '{kbx['lesson']['title']}' used: instant and verified")
                if job.visual:
                    job.visual["note"] = "this checked lesson has its own pictures, chosen when it was written"
                en = knowledge.assemble(info["kb"], p["level"], p["seconds"])
                if not en.scenes[0].art:
                    en.scenes[0].art = _title_art(info)
                build_full(job, en, lid, p, dict(info, facts=kbx["facts"]), "checked")
                job.status = "done"
                return
            try:
                model = planner.pick_model(p.get("model"))
            except planner.ModelUnavailable as e:
                raise ConnectionError(str(e))
            lid = _key("lesson", info["topic"].lower(), p["level"], p["seconds"], p["language"],
                       p["gender"], p["speed"], model)
            d = lesson_dir(lid)
            if not p.get("force") and (d / "meta.json").exists():
                job.notes.append("whole lesson loaded from history (instant)")
                job.playable(lid)
                job.mp4 = (d / "lesson.mp4").exists()
                if not job.mp4:
                    export_async(job, lid, d, json.loads((d / "timeline.json").read_text(encoding="utf-8"))["duration"])
                job.status = "done"
                return
            pf = config.DATA / "plans" / f"{_key('plan', info['topic'].lower(), p['level'], p['seconds'], model)}.json"
            if pf.exists() and not p.get("force"):
                job.notes.append("lesson plan loaded from cache: no LLM call")
                build_full(job, Lesson.model_validate_json(pf.read_text(encoding="utf-8")), lid, p, info, "cache",
                           {"model": model}, add_recap=False)
                job.status = "done"
                return
            try:
                en = _stream_build(job, info, p, model, lid, p["seconds"])
            except NoContent as e:
                # nothing usable from the AI (already retried once with reasons): checked lesson if the
                # topic matches one well, else an honest message; never an unrelated lesson
                cause = e.args[0]
                raise ConnectionError(str(cause)) if isinstance(cause, ConnectionError) else \
                    _Fallback(f"{type(cause).__name__}: {cause}"[:300])
            except (PlanTooShort, TimeoutError, ValueError) as e:
                if job.lesson_id:
                    raise
                if isinstance(e, PlanTooShort) and len(e.args) > 1 and e.args[1]:
                    # one retry that tells the model exactly what was wrong (same length)
                    job.notes.append("retrying once with feedback: " + "; ".join(e.args[1][:3]))
                    en = _stream_build(job, dict(info, feedback=e.args[1]), p, model, lid, p["seconds"])
                else:
                    # second chance: a shorter plan is much quicker for a slow CPU
                    job.notes.append(f"retrying with a shorter plan ({type(e).__name__}: {str(e)[:100]})")
                    en = _stream_build(job, info, p, model, lid, 30)
            pf.parent.mkdir(parents=True, exist_ok=True)
            pf.write_text(en.model_dump_json(indent=2), encoding="utf-8")
            job.status = "done"
    except NoFallback as e:
        job.error, job.status = str(e), "error"
        return
    except Exception as e:
        log.error(traceback.format_exc())
        why = f"{type(e).__name__}: {e}"
        if job.lesson_id and not isinstance(e, (_Fallback, ConnectionError)):
            # something failed after real lesson content was playing
            job.error, job.status = why, "error"
            return
        try:
            with _run_lock:
                _play_fallback(job, info or topic_nlp.basic(p["topic"]), p, why)
            job.status = "done"
        except NoFallback as e2:
            job.error, job.status = str(e2), "error"
        except Exception as e2:
            log.error(traceback.format_exc())
            job.error, job.status = f"{why} / fallback failed: {e2}", "error"


def _src_meta(lesson_id):
    f = lesson_dir(lesson_id) / "meta.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _info_from_meta(m, en):
    return {"topic": m.get("topic", en.title), "original": m.get("original", en.title), "fixes": m.get("fixes", []),
            "domain": m.get("domain", en.domain), "kb": m.get("kb"), "key_terms": m.get("key_terms", []),
            "facts": m.get("facts_used", [])}


def run_revoice(job: Job):
    """Same lesson, new language or voice: reuses the English plan, no LLM call."""
    p = job.params
    try:
        with _run_lock:
            job.status = "running"
            src = lesson_dir(p["lesson_id"])
            en = Lesson.model_validate_json((src / "lesson.en.json").read_text(encoding="utf-8"))
            m = _src_meta(p["lesson_id"])
            info = _info_from_meta(m, en)
            job.info = info
            q = {"language": p["language"], "gender": p["gender"], "speed": p["speed"], "level": en.level,
                 "seconds": m.get("target_seconds"), "topic": info["topic"]}
            lid = _key("revoice", p["lesson_id"], p["language"], p["gender"], p["speed"])
            if (lesson_dir(lid) / "meta.json").exists():
                job.notes.append("loaded from history (instant)")
                job.playable(lid)
                job.mp4 = (lesson_dir(lid) / "lesson.mp4").exists()
                job.status = "done"
                return
            job.notes.append("revoiced from the same English plan: no LLM call")
            build_full(job, en, lid, q, info, "revoice", {"model": m.get("model")}, add_recap=False)
            job.status = "done"
    except Exception as e:
        log.error(traceback.format_exc())
        job.error, job.status = f"{type(e).__name__}: {e}", "error"


def run_edit(job: Job):
    """Teacher edited one scene: only the changed sentences are re-voiced (clip cache), then re-export."""
    p = job.params
    try:
        with _run_lock:
            job.status = "running"
            d = lesson_dir(p["lesson_id"])
            m = _src_meta(p["lesson_id"])
            lang = m.get("language", "en")
            loc = Lesson.model_validate_json((d / f"lesson.{lang}.json").read_text(encoding="utf-8"))
            en = Lesson.model_validate_json((d / "lesson.en.json").read_text(encoding="utf-8"))
            data = loc.model_dump()
            data["scenes"][p["scene_index"]] = p["scene"]
            loc = Lesson.model_validate(data)            # validation errors go back to the teacher
            if lang == "en":
                en = loc
            info = _info_from_meta(m, en)
            q = {"language": lang, "level": loc.level, "seconds": m.get("target_seconds"), "topic": info["topic"],
                 **m.get("voice", {"gender": "female", "speed": 1.0})}
            job.notes.append(f"scene {p['scene_index'] + 1} edited; unchanged sentences reuse their audio")
            build_full(job, en, p["lesson_id"], q, info, m.get("source", "edit"), {"model": m.get("model")},
                       loc=loc, add_recap=False, fit=False)
            job.status = "done"
    except Exception as e:
        log.error(traceback.format_exc())
        job.error, job.status = f"{type(e).__name__}: {e}", "error"


def prebake(name, lang, level="beginner", seconds=60, gender="female", speed=1.0, mp4=False):
    """Build a ready-made fallback lesson before the demo (same id the fallback path looks for)."""
    p = {"language": lang, "level": level, "seconds": seconds, "gender": gender, "speed": speed, "export": mp4,
         "topic": knowledge.get(name)["lesson"]["title"]}
    job = Job("prebake", p)
    kb = knowledge.get(name)
    info = {"topic": kb["lesson"]["title"], "domain": kb["domain"], "kb": name, "facts": kb["facts"], "key_terms": []}
    build_full(job, knowledge.assemble(name, level, seconds), fallback_lesson_id(name, p), p, info, "library")
    return job


def history(limit=200):
    out = []
    for f in config.LESSONS_DIR.glob("*/meta.json"):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        m["mp4"] = (f.parent / "lesson.mp4").exists()
        out.append({k: m.get(k) for k in ("id", "title", "topic", "level", "language", "domain", "duration",
                                          "target_seconds", "source", "created", "model", "mp4")})
    return sorted(out, key=lambda m: m.get("created") or "", reverse=True)[:limit]


def delete_lesson(lesson_id: str) -> bool:
    """Delete one lesson folder, and nothing else (shared caches are kept)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", lesson_id or ""):
        raise ValueError("bad lesson id")
    root = config.LESSONS_DIR.resolve()
    d = (root / lesson_id).resolve()
    if d.parent != root or not d.is_dir():
        return False
    shutil.rmtree(d)
    return True


def clear_history() -> int:
    n = 0
    for f in list(config.LESSONS_DIR.glob("*/meta.json")):
        if delete_lesson(f.parent.name):
            n += 1
    return n


def start(kind, params) -> Job:
    job = Job(kind, params)
    fn = {"generate": _measured(run_generate), "revoice": _measured(run_revoice), "edit": _measured(run_edit)}[kind]
    threading.Thread(target=fn, args=(job,), daemon=True).start()
    return job
