"""Stage 2: the local LLM writes the lesson plan as JSON (data only, never code we run).

What makes it fast and on-topic on a CPU laptop:
  * a dynamic JSON schema per request (schema.llm_schema): only the scene types that suit the
    subject, and exactly as many scenes/sentences as the chosen length needs
  * subject rules + checked facts from the offline knowledge base in the prompt (local RAG)
  * streaming: every scene is handed to the pipeline the moment its JSON closes, so it can be
    translated, voiced and PLAYED while the model is still writing the next scene
  * a constant system prompt, so Ollama reuses its cached prefix
  * small mistakes are repaired in code instead of paying for a slow retry
"""
import json
import logging
import re
import time

import requests
from pydantic import ValidationError

from . import config, knowledge
from .schema import DOMAIN_SCENES, SCENE_TYPES, SceneAdapter, lesson_shape, llm_schema

log = logging.getLogger("planner")

SYSTEM = """You are an expert teacher who writes short animated video lessons for students in India.
Return ONLY compact JSON that matches the schema. No markdown, no comments.

Rules for every lesson:
- Do NOT write a title card: it is made for you. Start with the first teaching scene. Scenes teach step
  by step, each building on the last. The last scene is a "quiz" whose answer was taught in the lesson.
- Headings of teaching scenes start with "Step 1:", "Step 2:" and so on.
- narration is a list of beats. Each beat is ONE spoken sentence.
  "focus" is the index of the thing on screen that the sentence talks about:
  code line number (from 1), or diagram item / timeline event / worked-example step / chart bar /
  quiz option index (from 0). In a quiz, the last beat reveals the answer with focus = answer index.
- Narration is SPOKEN: write "range of three", not "range(3)"; "x squared", not "x^2". No symbols.
- Quiz options are plain text without "A)" or "1." prefixes. Do not read the options aloud.
- Diagram items are short labels (max 4 words). Give one emoji per item in "icons".
  For flow and cycle diagrams give "edge_labels": 1 to 3 words on each arrow.
- An "illustration" is a picture: one part with role "main" in the centre (e.g. a plant), "in" parts that flow
  into it (sun, water, carbon dioxide), "out" parts that come out of it (glucose, oxygen) and "part" labels for
  its pieces. "art" must be one of the drawing names in the schema; "via" is 1-3 words on the arrow.
  Show the whole process correctly (for example, never leave carbon dioxide out of photosynthesis).
- A "table" compares things: "columns" are the headers, "rows" are lists of short cells, one row per sentence.
- A "shape" is an exact figure (circle, triangle, right_triangle, square, rectangle, polygon, angle): list the
  parts to name in teaching order (e.g. centre, radius, diameter, circumference) with short labels and values.
- Be factually correct. Prefer the facts given. Simple, clear English (it will be translated)."""

DOMAIN_RULES = {
    "programming": "Programming topic. You MUST include a code_walkthrough with short, correct, runnable code "
                   "(max 8 lines, max 40 characters per line) and its exact 'output'. Explain the code line by line "
                   "(focus = line number), then trace what happens with a flow diagram.",
    "biology": "Biology topic. NEVER use code. Use an illustration for a process with inputs and outputs, and diagrams: 'flow' for processes, 'cycle' for cycles, 'hub' for the "
               "parts of an organ or cell (item 0 is the whole, the others are its labelled parts). Use a timeline for stages.",
    "physics": "Physics topic. NEVER use code. Explain the idea with a diagram, then a worked_example with real numbers "
               "and units (problem, 2-4 lines of working, answer). Use a chart only for exact, simple data.",
    "chemistry": "Chemistry topic. NEVER use code. Use diagrams for the idea, a worked_example for equations or "
                 "calculations, and a chart only for well-known values.",
    "math": "Maths topic. NEVER use code. Teach with worked_example scenes: a problem, 2-4 short lines of working, "
            "and the answer. Check every calculation. The quiz has a numeric answer.",
    "earth": "Earth science topic. NEVER use code. Use an illustration or a cycle/flow diagram for processes, a timeline for stages, "
             "and a chart only for well-known data.",
    "history": "History topic. NEVER use code. Use a timeline of correct dates in order (label = year), and a "
               "diagram for causes and effects.",
    "general": "NEVER use code unless the topic is programming. Use diagrams, a timeline or a chart to show the idea.",
    "person": "This is about a PERSON. NEVER use code. Teach it as a short biography: who they are and why they "
              "matter (title card), a timeline of their life and career (label = year, only years you are sure of), "
              "a diagram of their main achievements or qualities, and a quiz about something taught. "
              "Do not invent statistics, records or quotes; if unsure of a number, leave it out.",
}

KIND_NOTE = {
    "person": "The topic is a person.",
    "place": "The topic is a place: explain where it is, what it is known for and why it matters.",
    "organisation": "The topic is an organisation: explain what it does, when and why it was formed, and its impact.",
    "unknown": "The topic may be a name, a local term or a thing. If you do not know it reliably, teach only what "
               "you are sure of and keep it general; never make up facts.",
}

LEVEL_GUIDE = {
    "beginner": "BEGINNER: the learner is new. Everyday words, one real-life example or analogy, only the core "
                "idea and the basic steps. Define every new term simply. No formulas or jargon.",
    "intermediate": "INTERMEDIATE: the learner knows the basics, do NOT re-explain them. Explain HOW and WHY it works, "
                    "use the correct technical terms, a realistic example with numbers or code, and one common "
                    "mistake or misconception. The quiz tests understanding, not recall.",
    "advanced": "ADVANCED: the learner is confident. Go deep: the mechanism or theory behind it, equations or "
                "complexity where relevant, an edge case or exception, and how it connects to related ideas. "
                "Use precise terms. The quiz needs reasoning or a calculation.",
}


SYSTEM_COMPACT = """You are an expert teacher who writes short animated video lessons for students in India.
Return ONLY compact JSON: {"title": "...", "scenes": [ ... ]} with ONE object per line of the visual plan, in order.
Keys of a scene object:
  h = short heading.  l = the labels shown on screen, in order.  s = the spoken sentences, in order;
  sentence 1 talks about label 1, sentence 2 about label 2, and so on.
Special scenes:
  picture: l like "main: Green plant", "in: Sunlight", "out: Oxygen" (main = centre, in = goes in, out = comes out)
  shape: l like "radius: radius r = 7 cm" (part name, then its label)
  timeline: l like "1947: India becomes independent"     chart: l like "Oceans: 97", and u = the unit
  code: c = short runnable code (max 8 lines), out = its exact printed output; sentence n explains line n
  worked example: p = the problem, l = the steps of working, ans = the answer
  table: l = rows with cells split by " | "; the FIRST row is the header (e.g. "Property | Acid | Base"),
    then one row per sentence (e.g. "Taste | Sour | Bitter")
  quiz (always last): q = question, o = 3 options, a = index of the right option; s = 2 sentences, the 2nd gives the answer
Rules: sentences are SPOKEN (say "x squared", not "x^2"), one idea each, simple clear English (it is translated).
Be factually correct; prefer the facts given; never invent numbers, dates or quotes. Stay on the topic."""


def compact_schema(vp: dict, seconds: int, level: str) -> dict:
    """A small JSON schema for the compact format (much less to write than full scene objects)."""
    shape = lesson_shape(seconds, level)
    n = len(vp["scenes"]) - 1                                    # planned scenes after the title card
    strs = lambda mx, ml: {"type": "array", "items": {"type": "string", "maxLength": ml}, "maxItems": mx}
    says = {"type": "array", "items": {"type": "string", "maxLength": 170}, "minItems": 2,
            "maxItems": max(2, shape["beats_max"])}
    labels = dict(strs(6, 44), minItems=2)
    teach = {"type": "object", "properties": {
        "h": {"type": "string", "maxLength": 60}, "l": labels,
        "p": {"type": "string", "maxLength": 140}, "c": {"type": "string", "maxLength": 400}, "out": strs(6, 60),
        "ans": {"type": "string", "maxLength": 60}, "u": {"type": "string", "maxLength": 12}, "s": says},
        "required": ["h", "l", "s"]}                                  # labels are required: they ARE the picture
    quiz = {"type": "object", "properties": {
        "h": {"type": "string", "maxLength": 30}, "q": {"type": "string", "maxLength": 140},
        "o": dict(strs(4, 50), minItems=3), "a": {"type": "integer", "minimum": 0, "maximum": 3}, "s": says},
        "required": ["h", "q", "o", "a", "s"]}
    item = {"oneOf": [teach, quiz]}                                  # oneOf: already proven with Ollama
    return {"type": "object", "properties": {"title": {"type": "string", "maxLength": 80},
                                             "scenes": {"type": "array", "items": item,
                                                        "minItems": max(2, n - 1), "maxItems": n}},
            "required": ["title", "scenes"]}


def _split(x, default=""):
    a, sep, b = str(x).partition(":")
    return (a.strip(), b.strip()) if sep else (default, str(x).strip())


FILLER = re.compile(r"^(so|then|now|first|next|finally|also|here|this|these|it|there|we|you)\b[ ,]*", re.I)


def label_from(sentence: str) -> str:
    """A short on-screen label made from a spoken sentence (when the AI gave no labels)."""
    t = FILLER.sub("", str(sentence).strip()).strip(" .,!?:;")
    words = t.split()
    out = ""
    for w in words:
        if len(out) + len(w) + 1 > 38 or len(out.split()) >= 6:
            break
        out = (out + " " + w).strip()
    return (out[:1].upper() + out[1:]) if out else str(sentence)[:38]


def expand_compact(c: dict, ps: dict, step_no: int):
    """Compact scene from the AI + its planned scene -> a full scene dict (then repaired and validated).

    Never throws content away: missing labels are made from the sentences, and a planned scene whose
    special data (code, numbers, dates) is missing becomes a labelled diagram of the same sentences."""
    t = ps.get("type", "diagram")
    labels = [str(x) for x in (c.get("l") or []) if str(x).strip()]
    says = [str(x) for x in (c.get("s") or []) if str(x).strip()]
    if t != "quiz" and len(labels) < 2 and len(says) >= 2:
        labels = [label_from(x) for x in says]
    if t == "quiz" and not (c.get("q") and c.get("o") and isinstance(c.get("a"), int)):
        t = "diagram"                                               # a "quiz" without a question: keep the facts
        labels = labels or [label_from(x) for x in says]
        c = dict(c, h=c.get("h") if str(c.get("h", "")).lower() != "quick check" else "Key points")
    if t == "code_walkthrough" and not str(c.get("c") or "").strip():
        t = "diagram"
    if t == "worked_example" and len(labels) < 2:
        t = "diagram"
    if t == "timeline" and sum(":" in x for x in labels) < 2:
        t = "diagram"
    if t == "chart" and sum(bool(re.search(r":\s*-?\d", x)) for x in labels) < 2:
        t = "diagram"
    if t == "table" and sum("|" in x for x in labels) < 3:
        t = "diagram"                                              # no real rows: keep it as a labelled list
    if t == "shape":
        from .schema import SHAPES
        if not any(_split(x)[0].lower().replace(" ", "_") in SHAPES.get(ps.get("shape", "circle"), ()) for x in labels):
            t = "diagram"
    if t != "quiz" and str(c.get("h", "")).strip().lower() in ("quick check", "quiz"):
        c = dict(c, h="Key points")                             # not a real quiz: do not call it one
    ps = dict(ps, type=t)
    head = str(c.get("h") or ps.get("purpose") or "").strip()[:80]
    if t != "quiz" and not head.lower().startswith("step"):
        head = f"Step {step_no}: {head}"
    beat = lambda i, n: {"text": says[i], "focus": min(i, n - 1) if n else None}
    if t == "quiz":
        opts = [str(o) for o in (c.get("o") or [])][:4]
        a = c.get("a") if isinstance(c.get("a"), int) else None
        nar = [{"text": x} for x in says]
        if nar and a is not None:
            nar[-1]["focus"] = a
        return {"type": "quiz", "heading": "Quick check", "question": c.get("q") or "", "options": opts,
                "answer": a, "narration": nar}
    if t == "code_walkthrough":
        code = str(c.get("c") or "").rstrip()
        n = len(code.splitlines())
        return {"type": t, "heading": head, "code": code, "code_language": "python", "output": c.get("out") or None,
                "narration": [{"text": x, "focus": min(i + 1, max(1, n))} for i, x in enumerate(says)]}
    if t == "worked_example":
        steps = labels[:6]
        if len(steps) == 1 and c.get("ans"):
            steps.append(f"Answer: {c['ans']}")                  # a one-line working still teaches
        return {"type": t, "heading": head, "problem": c.get("p") or (labels[0] if labels else head),
                "steps": steps, "answer": c.get("ans") or "",
                "narration": [beat(i, len(labels)) for i in range(len(says))]}
    if t == "timeline":
        ev = []
        for i, x in enumerate(labels[:6]):
            lab, txt = _split(x, str(i + 1))
            ev.append({"label": lab[:20] or str(i + 1), "text": txt[:70]})
        return {"type": t, "heading": head, "events": ev, "narration": [beat(i, len(ev)) for i in range(len(says))]}
    if t == "chart":
        labs, vals = [], []
        for x in labels[:8]:
            lab, num = _split(x)
            m = re.search(r"-?\d+(\.\d+)?", num)
            if m:
                labs.append(lab[:30] or num)
                vals.append(float(m.group(0)))
        return {"type": t, "heading": head, "chart_title": head[:60], "labels": labs, "values": vals,
                "unit": (c.get("u") or None), "narration": [beat(i, len(labs)) for i in range(len(says))]}
    if t == "table":
        grid = [[x.strip() for x in row.split("|")] for row in labels if "|" in row]
        cols, rows = grid[0][:4], grid[1:6]
        return {"type": t, "heading": head, "columns": cols, "rows": [r[:len(cols)] for r in rows],
                "narration": [{"text": says[i], "focus": min(i, len(rows) - 1)} for i in range(len(says))]}
    if t == "illustration":
        from .visual_plan import pictures_for
        arts = list(ps.get("art") or [])
        parts = []
        for i, x in enumerate(labels[:6]):
            role, lab = _split(x, "part")
            role = role.lower() if role.lower() in ("main", "in", "out", "part") else "part"
            found = pictures_for(lab, 1)
            art = found[0] if found else (arts[i] if i < len(arts) else "dot")
            parts.append({"art": art, "label": lab[:32], "role": "main" if (i == 0 and role == "part") else role})
        return {"type": t, "heading": head, "parts": parts, "narration": [beat(i, len(parts)) for i in range(len(says))]}
    if t == "shape":
        parts = []
        for x in labels[:6]:
            part, lab = _split(x)
            parts.append({"part": part or lab, "label": (lab or part)[:28]})
        out = {"type": t, "heading": head, "shape": ps.get("shape", "circle"), "parts": parts,
               "narration": [beat(i, len(parts)) for i in range(len(says))]}
        if ps.get("sides"):
            out["sides"] = ps["sides"]
        return out
    return {"type": "diagram", "heading": head, "layout": ps.get("layout") or "flow", "items": [x[:40] for x in labels[:7]],
            "narration": [beat(i, len(labels)) for i in range(len(says))]}


def _example_scene(domain: str) -> str:
    """One short scene of the subject's core type, taken from the knowledge base."""
    core = DOMAIN_SCENES.get(domain, DOMAIN_SCENES["general"])[0]
    for kb in knowledge.all_topics().values():
        if kb["domain"] == domain or domain == "general":
            for sc in kb["lesson"]["scenes"]:
                if sc["type"] == core:
                    sc = {k: v for k, v in sc.items() if k != "levels"}
                    return json.dumps(sc, ensure_ascii=False, separators=(",", ":"))
    return ""


def build_prompt(info: dict, level: str, seconds: int, compact: bool = False) -> str:
    """The structured topic from the NLP stage becomes a short 'topic card' for the model."""
    shape = lesson_shape(seconds, level)
    domain = info["domain"]
    lines = [f"Topic: {info['topic']}", f"Subject: {domain}", f"Level: {level}"]
    if info.get("original") and info["original"].strip().lower() != info["topic"].strip().lower():
        lines.append(f"The learner typed: \"{info['original']}\" (understood as the topic above).")
    if info.get("kind") in KIND_NOTE:
        lines.append(KIND_NOTE[info["kind"]])
    if info.get("intent"):
        lines.append(f"The learner wants: {info['intent']}.")
    if info.get("entities"):
        lines.append("Named entities: " + ", ".join(f"{e['text']} ({e['type']})" for e in info["entities"]))
    lines += [LEVEL_GUIDE[level], DOMAIN_RULES.get(domain, DOMAIN_RULES["general"])]
    if info.get("key_terms"):
        lines.append("Key terms: " + ", ".join(info["key_terms"]))
    if info.get("facts"):
        src = knowledge.get(info.get("kb"))
        lines.append("Checked facts" + (f" (source: offline notes '{src['lesson']['title']}')" if src else "")
                     + " - use them, never contradict them:\n- " + "\n- ".join(info["facts"]))
    elif info.get("related") and knowledge.get(info["related"]):
        rel = knowledge.get(info["related"])
        lines.append(f"Possibly related checked notes ('{rel['lesson']['title']}'), background only - use a fact "
                     "ONLY if it is really about this topic:\n- " + "\n- ".join(rel["facts"][:3]))
        lines.append("Otherwise use only well-established facts, avoid exact numbers and dates unless you are "
                     "certain, and stay strictly on the topic.")
    else:
        lines.append("No checked notes exist for this topic: use only well-established facts, avoid exact "
                     "numbers and dates unless you are certain, and stay strictly on the topic.")
    lines.append(
        f"Length: about {seconds} seconds. Write {shape['scenes'] - 1} scenes: "
        f"{shape['scenes'] - 2} teaching scenes, then 1 quiz. Each teaching scene has {shape['beats_max']} sentences "
        f"of about {shape['words_per_beat']} words.")
    if compact and info.get("visual"):
        lines.append("Visual plan (one JSON scene object per line, in this order):")
        n = 0
        for ps in info["visual"]["scenes"][1:]:
            n += 1
            kind = {"illustration": "picture", "worked_example": "worked example", "code_walkthrough": "code",
                    "table": "table"}.get(
                ps["type"], ps["type"])
            extra = ""
            if ps.get("art"):
                extra = f" (drawings available: {', '.join(ps['art'])})"
            if ps.get("shape"):
                from .schema import SHAPES
                extra = f" ({ps['shape'].replace('_', ' ')}; parts: {', '.join(SHAPES[ps['shape']])})"
            short = " Keep THIS first scene short: exactly 2 sentences." if n == 1 and ps["type"] != "quiz" else ""
            lines.append(f"  {n}. {kind}{(' ' + ps['layout']) if ps.get('layout') else ''}: {ps['purpose']}{extra}{short}")
        if info.get("feedback"):
            lines.append("Your previous answer was not usable because: " + "; ".join(info["feedback"][:4])
                         + ". Fix this: every scene must be about the topic above.")
        return "\n".join(lines)
    if info.get("feedback"):
        lines.append("Your previous answer was not usable because: " + "; ".join(info["feedback"][:4])
                     + ". Fix this: every scene must be about the topic above.")
    if info.get("visual"):
        # visual reasoning already chose the scenes: the plan replaces the long example (shorter prompt = faster)
        from . import visual_plan
        lines.append(visual_plan.prompt_lines(info["visual"]))
    else:
        ex = _example_scene(domain)
        if ex:
            lines.append("Example of one good scene for this subject:\n" + ex)
    return "\n".join(lines)


# ------------------------------------------------------------------ incremental JSON scene parser

class SceneStream:
    """Feed it streamed text; it returns each top-level field value and each scene as soon as its
    JSON is complete. Works on the raw character stream, so it never waits for the whole answer."""

    def __init__(self):
        self.buf = ""
        self.i = 0
        self.depth = 0
        self.in_str = False
        self.esc = False
        self.str_start = None
        self.last_str = None
        self.key = None             # last key seen at depth 1
        self.scenes_depth = None    # depth inside the scenes array
        self.scene_start = None
        self.val_start = None

    def feed(self, text):
        self.buf += text
        events = []
        b = self.buf
        while self.i < len(b):
            c = b[self.i]
            if self.in_str:
                if self.esc:
                    self.esc = False
                elif c == "\\":
                    self.esc = True
                elif c == '"':
                    self.in_str = False
                    s = b[self.str_start:self.i + 1]
                    if self.depth == 1:
                        j = self.i + 1
                        while j < len(b) and b[j] in " \n\r\t":
                            j += 1
                        if j < len(b) and b[j] == ":":
                            self.key = json.loads(s)
                        elif j < len(b) and self.key == "title":
                            events.append(("title", json.loads(s)))
                        elif j >= len(b):
                            # can't tell yet if this is a key; re-scan this string next time
                            self.i, self.in_str = self.str_start, False
                            break
            else:
                if c == '"':
                    self.in_str, self.str_start = True, self.i
                elif c in "{[":
                    self.depth += 1
                    if c == "[" and self.depth == 2 and self.key == "scenes":
                        self.scenes_depth = 2
                    elif c == "{" and self.scenes_depth and self.depth == self.scenes_depth + 1:
                        self.scene_start = self.i
                    elif c == "[" and self.depth == 2:
                        self.val_start = self.i
                elif c in "}]":
                    if c == "}" and self.scenes_depth and self.depth == self.scenes_depth + 1 and self.scene_start is not None:
                        try:
                            events.append(("scene", json.loads(b[self.scene_start:self.i + 1])))
                        except json.JSONDecodeError:
                            pass
                        self.scene_start = None
                    if c == "]" and self.depth == 2:
                        if self.key == "scenes":
                            self.scenes_depth = None
                        elif self.val_start is not None:
                            try:
                                events.append((self.key, json.loads(b[self.val_start:self.i + 1])))
                            except json.JSONDecodeError:
                                pass
                            self.val_start = None
                    self.depth -= 1
            self.i += 1
        return events


# ------------------------------------------------------------------ repair (cheap, no LLM)

def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def repair_scene(sc: dict, title: str = "", allowed=None):
    """Fix the small mistakes small models make. Returns a valid scene model, or None."""
    if not isinstance(sc, dict) or sc.get("type") not in SCENE_TYPES:
        return None
    if allowed and sc["type"] not in allowed and sc["type"] != "title_card":
        return None
    nar = sc.get("narration")
    if isinstance(nar, str):
        nar = [{"text": t} for t in re.split(r"(?<=[.!?])\s+", nar) if t.strip()]
    beats, seen = [], set()
    for b in nar or []:
        b = {"text": b} if isinstance(b, str) else (b if isinstance(b, dict) else {})
        t = str(b.get("text") or "").strip()
        if len(t) < 2 or t.lower() in seen:            # drop empty and repeated sentences
            continue
        seen.add(t.lower())
        beats.append({"text": t[:400], "focus": _int(b.get("focus"))})
    if not beats:
        return None
    sc["narration"] = beats[:6]
    head = str(sc.get("heading") or "").strip()
    sc["heading"] = (head if len(head) >= 2 else (title or "Lesson"))[:90]
    t = sc["type"]

    def clamp(n, base=0):
        for b in beats:
            if b["focus"] is not None and not base <= b["focus"] < n + base:
                b["focus"] = None

    if t == "code_walkthrough":
        lines = str(sc.get("code") or "").replace("\t", "    ").rstrip().splitlines()[:14]
        if not lines:
            return None
        sc["code"] = "\n".join(lines)
        clamp(len(lines), 1)
        out = sc.get("output")
        sc["output"] = [str(o) for o in out][:8] if isinstance(out, list) else ([str(out)] if out else None)
    elif t == "diagram":
        items = [str(i)[:40] for i in (sc.get("items") or []) if str(i).strip()][:7]
        if len(items) < 2:
            return None
        sc["items"] = items
        if sc.get("layout") not in ("flow", "cycle", "stack", "hub"):
            sc["layout"] = "flow"
        for k in ("icons", "edge_labels"):
            if not isinstance(sc.get(k), list):
                sc[k] = None
        clamp(len(items))
    elif t == "timeline":
        ev = [e for e in (sc.get("events") or []) if isinstance(e, dict) and e.get("label") and e.get("text")][:6]
        if len(ev) < 2:
            return None
        sc["events"] = [{"label": str(e["label"])[:20], "text": str(e["text"])[:70]} for e in ev]
        clamp(len(ev))
    elif t == "chart":
        labels, values = sc.get("labels") or [], sc.get("values") or []
        pairs = []
        for l, v in zip(labels, values):
            try:
                pairs.append((str(l)[:30], float(v)))
            except (TypeError, ValueError):
                pass
        if len(pairs) < 2 or any(v < 0 for _, v in pairs):
            return None
        sc["labels"], sc["values"] = [p[0] for p in pairs[:8]], [p[1] for p in pairs[:8]]
        clamp(len(sc["labels"]))
    elif t == "worked_example":
        steps = [str(s)[:80] for s in (sc.get("steps") or []) if str(s).strip()][:6]
        if len(steps) < 2 or not sc.get("problem") or not sc.get("answer"):
            return None
        sc["steps"] = steps
        clamp(len(steps))
    elif t == "table":
        cols = [str(c)[:24] for c in (sc.get("columns") or [])][:4]
        rows = [[str(c)[:40] for c in r] for r in (sc.get("rows") or []) if isinstance(r, list)][:6]
        if len(cols) < 2 or len(rows) < 2:
            return None
        sc["columns"], sc["rows"] = cols, rows
        clamp(len(rows))
    elif t == "shape":
        parts = [{"part": str(x.get("part") or ""), "label": str(x.get("label") or x.get("part") or "")[:28]}
                 for x in (sc.get("parts") or []) if isinstance(x, dict) and (x.get("part") or x.get("label"))]
        if not parts:
            return None
        sc["parts"] = parts[:6]
        for k in ("sides", "degrees"):
            if sc.get(k) is not None:
                try:
                    sc[k] = int(sc[k]) if k == "sides" else float(sc[k])
                except (TypeError, ValueError):
                    sc[k] = None
        clamp(len(sc["parts"]))
    elif t == "illustration":
        parts = []
        for prt in sc.get("parts") or []:
            if isinstance(prt, dict) and str(prt.get("label") or "").strip():
                parts.append({"art": prt.get("art") or "dot", "label": str(prt["label"])[:32],
                              "role": prt.get("role") if prt.get("role") in ("main", "in", "out", "part") else "part",
                              "via": str(prt["via"])[:24] if prt.get("via") else None})
        if len(parts) < 2:
            return None
        sc["parts"] = parts[:6]
        clamp(len(sc["parts"]))
    elif t == "quiz":
        opts = [re.sub(r"^\s*(\(?[A-Da-d1-4][\).:]|[A-Da-d]\s*-)\s+", "", str(o)) for o in (sc.get("options") or [])][:4]
        ans = _int(sc.get("answer"))
        if len(opts) < 2 or ans is None or not 0 <= ans < len(opts) or not sc.get("question"):
            return None                                  # never guess a quiz answer
        sc["options"], sc["answer"] = opts, ans
        # a beat that just reads the options aloud adds nothing: drop it
        sc["narration"] = [b for b in beats if sum(o.lower() in b["text"].lower() for o in opts) < 3] or beats[:1]
        clamp(len(opts))
    try:
        return SceneAdapter.validate_python(sc)
    except ValidationError as e:
        log.warning("scene dropped after repair: %s", e.errors()[:2])
        return None


def make_recap(scenes):
    """An automatic recap scene built from the lesson's own steps (no LLM needed)."""
    steps = []
    for s in scenes:
        if s.type in ("title_card", "quiz") or s.heading == "Recap":
            continue
        h = re.sub(r"^Step \d+:\s*", "", s.heading).strip().rstrip(".")
        if h and h.lower() not in (x.lower() for x in steps):
            steps.append(h)
    steps = steps[:5]
    if len(steps) < 2:
        return None
    words = ["First", "Next", "Then", "After that", "Finally"]
    lead = words[:len(steps) - 1] + ["Finally"]
    beats = [{"text": "Let us recap what we learned."}]
    beats += [{"text": f"{lead[i]}: {h[0].lower() + h[1:]}.", "focus": i} for i, h in enumerate(steps)]
    return SceneAdapter.validate_python({"type": "diagram", "layout": "stack", "heading": "Recap",
                                         "items": [h[:40] for h in steps], "icons": ["✅"] * len(steps),
                                         "narration": beats[:6]})


# ------------------------------------------------------------------ streaming call

def stream_plan(info, level, seconds, model=None, on_title=None, on_scene=None, on_progress=None):
    """Streams the lesson. Calls on_scene(scene_model) for each valid scene as soon as it is complete.
    Returns {"title", "prerequisites", "next_topics", "raw", "tokens", "tps"}. Raises on failure."""
    model = model or config.OLLAMA_MODEL
    allowed = set(["title_card"] + DOMAIN_SCENES.get(info["domain"], DOMAIN_SCENES["general"]))
    shape = lesson_shape(seconds, level)
    expected = shape["words"] * 1.9 + (shape["scenes"] - 1) * 60
    vp = info.get("visual")
    compact = bool(vp) and config.COMPACT
    if compact:
        expected = shape["words"] * 1.45 + (shape["scenes"] - 1) * 30      # far fewer tokens to write
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_COMPACT if compact else SYSTEM},
                     {"role": "user", "content": build_prompt(info, level, seconds, compact=compact)}],
        "format": compact_schema(vp, seconds, level) if compact else
        llm_schema(info["domain"], seconds, level, (vp or {}).get("types"), no_title=True),
        "stream": True,
        "keep_alive": -1,
        # num_predict: room for this length only, so a confused model cannot write for minutes
        "options": {"temperature": 0.3, "num_ctx": 4096, "num_predict": int(min(1600, expected * 1.6 + 200))},
    }
    if model.startswith(("qwen3", "deepseek-r1")):
        body["think"] = False
    out = {"title": None, "prerequisites": [], "next_topics": [], "raw": "", "tokens": 0, "tps": 0.0}
    parser = SceneStream()
    t0 = time.perf_counter()
    with requests.post(f"{config.OLLAMA_URL}/api/chat", json=body, stream=True,
                       timeout=(10, config.PLANNER_STALL_S)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            d = json.loads(line)
            if d.get("error"):
                raise RuntimeError(d["error"])
            piece = d.get("message", {}).get("content", "")
            out["raw"] += piece
            out["tokens"] += 1
            if on_progress:
                on_progress(min(0.99, out["tokens"] / expected))
            for kind, val in parser.feed(piece):
                if kind == "title" and isinstance(val, str):
                    out["title"] = val[:90]
                    if on_title:
                        on_title(out["title"])
                elif kind == "scene":
                    if compact and isinstance(val, dict) and "type" not in val:
                        planned = vp["scenes"][1:]                   # teaching scenes, then the quiz
                        k = out.get("_n", 0)
                        out["_n"] = k + 1
                        if val.get("q") or val.get("o"):
                            ps = planned[-1]                         # a quiz is always the planned last scene
                        else:
                            ps = planned[min(k, len(planned) - 2)] if len(planned) > 1 else planned[0]
                        val = expand_compact(val, ps, k + 1)
                        allowed = allowed | {val.get("type", ps["type"])}
                    sc = repair_scene(val, out["title"] or info["topic"], allowed)
                    if sc is None:
                        out["dropped"] = out.get("dropped", 0) + 1
                    if sc is not None and on_scene:
                        on_scene(sc)
                elif kind in ("prerequisites", "next_topics") and isinstance(val, list):
                    out[kind] = [str(v)[:60] for v in val if str(v).strip()][:3]
            if time.perf_counter() - t0 > config.PLANNER_TIMEOUT_S:
                raise TimeoutError(f"LLM still writing after {config.PLANNER_TIMEOUT_S}s")
            if d.get("done"):
                break
    out.pop("_n", None)
    out["tps"] = round(out["tokens"] / max(0.1, time.perf_counter() - t0), 1)
    log.info("planner: %d tokens, %.1f tokens/s", out["tokens"], out["tps"])
    return out


class ModelUnavailable(RuntimeError):
    pass


PREFERRED = ["phi4-mini", "qwen2.5:1.5b", "qwen3:1.7b", "qwen3:4b", "llama3.2:3b", "gemma3:4b", "qwen2.5:3b", "phi3:mini"]


def pick_model(requested=None):
    """Use the configured model if it is installed, else the best installed one. Never a missing model."""
    try:
        r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        r.raise_for_status()
    except Exception as e:
        raise ModelUnavailable("Ollama is not running. Open the Ollama app (or run 'ollama serve') and try again.") from e
    names = [m["name"] for m in r.json().get("models", [])]
    base = {n.removesuffix(":latest"): n for n in names}
    fast = [config.FAST_MODEL] if config.SPEED_MODE == "fast" else []
    for want in [requested] + fast + [config.OLLAMA_MODEL] + PREFERRED:
        if want and (want in names or want in base):
            return base.get(want, want)
    chat = [n for n in names if not n.startswith(("nomic-embed", "mxbai-embed", "all-minilm"))]
    if chat:
        return chat[0]
    raise ModelUnavailable("No language model is installed in Ollama. Run: ollama pull phi4-mini")


def ask_scene(info, level, seconds, model, have_headings, step_no):
    """Smart validation: ask the model for ONE replacement scene (bounded, used at most once or twice)."""
    allowed = [t for t in DOMAIN_SCENES.get(info["domain"], DOMAIN_SCENES["general"]) if t != "quiz"]
    full = llm_schema(info["domain"], seconds, level)
    scene_schema = {"$defs": full["$defs"], **full["properties"]["scenes"]["items"]}
    scene_schema["oneOf"] = [x for x in scene_schema["oneOf"] if any(x["$ref"].lower().endswith(t.replace("_", ""))
                                                                     for t in allowed)] or scene_schema["oneOf"]
    prompt = (build_prompt(info, level, seconds) + "\n\nWrite ONLY ONE new teaching scene (not a title card, not a quiz) "
              f"with heading 'Step {step_no}: ...'. It must teach something not already covered by: "
              + "; ".join(have_headings) + ".")
    body = {"model": model, "stream": False, "keep_alive": -1, "format": scene_schema,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            "options": {"temperature": 0.4, "num_ctx": 4096, "num_predict": 450}}
    if model.startswith(("qwen3", "deepseek-r1")):
        body["think"] = False
    r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=(10, config.PLANNER_STALL_S))
    r.raise_for_status()
    try:
        return repair_scene(json.loads(r.json()["message"]["content"]), info["topic"],
                            set(["title_card"] + DOMAIN_SCENES.get(info["domain"], DOMAIN_SCENES["general"])))
    except (json.JSONDecodeError, KeyError):
        return None


def installed_models():
    """Models available in the local Ollama, for the model picker."""
    try:
        r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []
