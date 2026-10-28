"""Offline knowledge base (backend/knowledge/*.json).

Each topic file holds:
  * keywords      - used to recognise the topic
  * facts         - short, checked facts given to the LLM so the lesson stays correct (local RAG)
  * prerequisites / next_topics - the learning path shown after the lesson
  * lesson        - a hand-checked lesson whose scenes are tagged by level; used as the fallback,
                    assembled to the requested level and length
"""
import copy
import json
import re
from functools import lru_cache
from pathlib import Path

from .schema import LEVELS, Lesson, lesson_shape

KB_DIR = Path(__file__).resolve().parent / "knowledge"


@lru_cache(maxsize=1)
def all_topics() -> dict:
    out = {}
    for f in sorted(KB_DIR.glob("*.json")):
        kb = json.loads(f.read_text(encoding="utf-8"))
        kb["_kw"] = set(kb["keywords"].split())
        out[kb["id"]] = kb
    return out


def get(topic_id):
    return all_topics().get(topic_id)


def match(words) -> tuple:
    """Best topic for a set of lower-case words: (id, score). Score 0 means no match."""
    words = set(words)
    best, score = None, 0
    for tid, kb in all_topics().items():
        s = len(words & kb["_kw"])
        if s > score:
            best, score = tid, s
    return best, score


def vocabulary() -> set:
    v = set()
    for kb in all_topics().values():
        v |= kb["_kw"]
    return v


def _est(sc):
    """Rough spoken length of a scene (same model as schema.lesson_shape: 2.6 words/s)."""
    words = sum(len(b["text"].split()) for b in sc["narration"])
    return 1.6 + words / 2.6 + 0.25 * len(sc["narration"])


def _drop_one(sc, keep_min=2):
    """Remove one sentence: first one that does not point at anything, else the second-to-last."""
    nb = sc["narration"]
    if len(nb) <= keep_min:
        return False
    plain = [i for i, b in enumerate(nb[:-1]) if b.get("focus") is None and i > 0]
    nb.pop(plain[0] if plain else len(nb) - 2)
    return True


def _fit_narration(scenes, seconds):
    """Checked scenes are written once for every length: fit them to this length.

    Only trims when the lesson would run long (> 8 % over): long scenes first, a written short
    version before cutting sentences (so a picture never loses e.g. carbon dioxide)."""
    body = [sc for sc in scenes[1:] if sc["type"] != "quiz"]
    while sum(_est(sc) for sc in scenes) > seconds * 1.08:
        cands = sorted(body, key=lambda sc: -_est(sc))
        done = False
        for sc in cands:
            if sc.get("short") and len(sc["short"]) < len(sc["narration"]):
                sc["narration"] = sc["short"]
                done = True
                break
            if not sc.get("short") and _drop_one(sc):
                done = True
                break
        if not done:
            break
    for sc in scenes:
        sc.pop("short", None)


def _renumber(scenes):
    n = 0
    for sc in scenes:
        if re.match(r"^Step \d+:", sc["heading"]):
            n += 1
            sc["heading"] = re.sub(r"^Step \d+:", f"Step {n}:", sc["heading"])


def assemble(topic_id: str, level: str = "beginner", seconds: int = 60) -> Lesson:
    """Build the fallback lesson for this level and length from the level-tagged scenes."""
    kb = get(topic_id) or get("python_loop")
    level = level if level in LEVELS else "beginner"
    scenes = [copy.deepcopy(s) for s in kb["lesson"]["scenes"] if level in s.get("levels", LEVELS)]
    for s in scenes:
        s.pop("levels", None)
    title = scenes[0]
    quiz = scenes[-1] if scenes[-1]["type"] == "quiz" else None
    middle = scenes[1:-1] if quiz else scenes[1:]
    want = max(1, lesson_shape(seconds, level)["scenes"] - 1 - (1 if quiz else 0))
    if len(middle) > want:
        # beginners keep the core ideas first; higher levels keep the scenes written for their level;
        # very short lessons (30 s) prefer the shorter scenes so the whole video still fits
        tagged = [i for i, s in enumerate(kb["lesson"]["scenes"]) if level in s.get("levels", LEVELS)]
        words = [sum(len(b["text"].split()) for b in s["narration"]) for s in middle]
        short = seconds <= 35
        if level == "beginner":
            order = sorted(range(len(middle)), key=lambda i: (words[i] if short else 0, i))
        else:
            order = sorted(range(len(middle)),
                           key=lambda i: (len(kb["lesson"]["scenes"][tagged[i + 1]].get("levels", LEVELS)),
                                          words[i] if short else 0, i))
        keep = sorted(order[:want])
        middle = [middle[i] for i in keep]
    spare = [copy.deepcopy(s) for s in kb["lesson"]["scenes"][1:]
             if s["type"] != "quiz" and level not in s.get("levels", LEVELS)]
    spare.sort(key=lambda s: len(s.get("levels", LEVELS)), reverse=True)     # the closest level first
    if len(middle) < 2:
        # every lesson needs 3+ scenes after the title: borrow the nearest scenes written for another level
        for s in spare[: 2 - len(middle)]:
            s.pop("levels", None)
            middle.append(s)
        spare = spare[2:]
    est = lambda: sum(_est(x) for x in [title] + middle + ([quiz] if quiz else []))
    borrowed = 0
    while spare and borrowed < 2 and len(middle) < 6 and est() < seconds * 0.8:
        # a long lesson with little material at this level: add "a closer look" from the next level
        s = spare.pop(0)
        s.pop("levels", None)
        s["heading"] = re.sub(r"^(Step \d+:)\s*", r"\1 A closer look: ", s["heading"])
        middle.append(s)
        borrowed += 1
    out = [title] + middle + ([quiz] if quiz else [])
    _fit_narration(out, seconds)
    _renumber(out)
    return Lesson.model_validate({
        "title": kb["lesson"]["title"], "level": level, "language": "en", "domain": kb["domain"],
        "scenes": out, "prerequisites": kb.get("prerequisites", []), "next_topics": kb.get("next_topics", [])})
