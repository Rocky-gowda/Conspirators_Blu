"""Visual reasoning: before the AI writes a word, decide which picture best explains each part of
this lesson, and why. Offline, rule-based, instant.

The plan is chosen from what the topic *is* (a process with inputs and outputs, a cycle, a structure
with parts, a sequence of steps, events in time, a calculation, code, a comparison of amounts), the
learner's level and the chosen length. It is then:
  * written into the AI prompt as a scene-by-scene plan (with the drawings to use),
  * used to limit the JSON schema to the planned scene types (less to decide = faster on a CPU),
  * checked against what the AI actually wrote, and shown to the learner ("why this picture").
"""
import re

from . import schema
from .schema import ART, ART_ALIASES, lesson_shape

# words that reveal the *shape* of an idea
CUES = {
    "process": r"\b(make|makes|made|produce|produces|convert|converts|turn|turns|absorb|absorbs|release|releases|"
               r"take in|takes in|give out|gives out|input|output|digest|digestion|respiration|photosynthesis|"
               r"generate|generates|transform|combustion|burn|burns|charge|power|powers)\b",
    "cycle": r"\b(cycle|cycles|circulation|circulates|rotation|revolve|revolves|seasons?|life cycle|loop back|repeats?)\b",
    "parts": r"\b(parts?|structure|structures|organ|organs|chambers?|layers?|components?|anatomy|made of|consists?|"
             r"types of|kinds of|cell|cells|system|systems|heart|engine|machine)\b",
    "steps": r"\b(how|process|steps?|stages?|works?|working|method|procedure|algorithm|sequence|order)\b",
    "time": r"\b(history|historical|when|timeline|century|centuries|year|years|era|dynasty|empire|war|revolution|"
            r"independence|born|life of|biography|1[0-9]{3}|20[0-9]{2})\b",
    "calc": r"\b(calculate|calculation|formula|equation|solve|law|laws|theorem|speed|velocity|force|voltage|"
            r"current|resistance|area|volume|probability|percentage|ratio|density|pressure)\b",
    "amount": r"\b(how much|how many|compare amounts|population|rainfall|percent|percentage|statistics|data|"
              r"distribution|share of|most|least|largest|smallest)\b",
    "compare": r"\b(compare|comparison|difference|differences|vs|versus|similar|similarities|better|types)\b",
}

PICTURE_WORDS = {**{a: a for a in ART if a != "dot"}, **ART_ALIASES,
                 "carbon": "co2", "sugar": "glucose", "rain": "rain", "clouds": "cloud", "roots": "plant",
                 "battery": "battery", "bulb": "bulb", "circuit": "battery", "electrons": "atom",
                 "lungs": "lungs", "blood": "blood", "heart": "heart", "brain": "brain", "earth": "earth",
                 "moon": "moon", "stars": "star", "planets": "earth", "factory": "factory", "money": "coin",
                 "computer": "computer", "code": "code", "dna": "dna", "virus": "virus", "bacteria": "virus",
                 "vaccine": "virus", "vaccines": "virus", "antibodies": "blood", "immune": "person",
                 "muscles": "person", "stomach": "food", "food": "food", "salt": "salt", "acid": "beaker",
                 "rocket": "rocket", "magnet": "magnet", "heat": "heat", "energy": "heat", "wind": "wind",
                 "snow": "snow", "mountains": "mountain", "river": "water", "rivers": "water", "ocean": "sea",
                 "solar": "sun", "planet": "earth", "digestion": "food", "nutrients": "food", "engine": "gear",
                 "fuel": "heat", "voltage": "battery", "chlorophyll": "leaf", "fire": "heat", "flame": "heat"}
PICTURE_WORDS.pop("energy", None)       # "light energy" is the sun, not a flame


def pictures_for(text: str, limit: int = 6) -> list:
    """Drawings from the built-in library that match words in the topic and its checked facts."""
    low = " " + re.sub(r"[^a-z0-9 ]", " ", text.lower()) + " "
    hits = {}                                                         # art -> first position in the text
    for phrase in sorted(PICTURE_WORDS, key=len, reverse=True):      # "carbon dioxide" before "carbon"
        art = PICTURE_WORDS[phrase]
        if art not in ART or art == "dot":
            continue
        for form in (phrase, phrase + "s", phrase + "es", phrase[:-1] + "ies" if phrase.endswith("y") else None):
            if form and f" {form} " in low:
                hits.setdefault(art, low.index(f" {form} "))
                hits[art] = min(hits[art], low.index(f" {form} "))
                low = low.replace(f" {form} ", " " + "_" * len(form) + " ")   # keep positions
    if "plant" in hits:                                               # a leaf is part of the plant drawing
        hits.pop("leaf", None)
    return sorted(hits, key=hits.get)[:limit]                         # in the order the text mentions them


SHAPE_WORDS = [("right_triangle", r"right[- ]?angled? triangle|hypotenuse|pythagoras|pythagorean"),
               ("circle", r"\bcircles?\b|radius|diameter|circumference|\bchords?\b"),
               ("triangle", r"\btriangles?\b"), ("square", r"\bsquares?\b(?! root)"),
               ("rectangle", r"\brectangles?\b"), ("polygon", r"polygon|pentagon|hexagon|octagon"),
               ("angle", r"\bangles?\b")]


def _shape_for(text):
    for name, rx in SHAPE_WORDS:
        if re.search(rx, text):
            return name
    return None


def _shapes(text):
    return {k for k, rx in CUES.items() if re.search(rx, text)}


def plan(info: dict, level: str = "beginner", seconds: int = 60) -> dict:
    """-> {"scenes": [{"type", "layout"?, "purpose", "why", "art"?}], "types": [...], "summary": str}"""
    topic = info.get("topic", "")
    facts = " ".join(info.get("facts") or [])
    text = f"{topic} {' '.join(info.get('key_terms') or [])} {facts}".lower()
    domain, kind = info.get("domain", "general"), info.get("kind", "concept")
    # the topic decides the picture shape; the checked facts may only add "it is a process / it has numbers"
    # (a fact about the Calvin *cycle* must not turn photosynthesis into a cycle diagram)
    shapes = _shapes(topic.lower()) | (_shapes(facts.lower()) & {"process", "calc", "amount"})
    arts = pictures_for(f"{topic} {facts}")
    allowed = set(schema.DOMAIN_SCENES.get(domain, schema.DOMAIN_SCENES["general"]))
    n = max(1, lesson_shape(seconds, level)["scenes"] - 2)          # teaching scenes between title and quiz
    cand = []

    def add(t, purpose, why, layout=None, art=None):
        if t in allowed and not any(c["type"] == t and c.get("layout") == layout for c in cand):
            c = {"type": t, "purpose": purpose, "why": why}
            if layout:
                c["layout"] = layout
            if art:
                c["art"] = art
            cand.append(c)

    shape = _shape_for(topic.lower())
    if shape:
        # a shape is understood by seeing it drawn exactly, part by part
        add("shape", f"draw the {shape.replace('_', ' ')} and name its parts in order",
            f"“{topic}” is a shape: it is drawn exactly and each part is named as it appears",
            layout=None, art=None)
        cand[-1]["shape"] = shape
        n_sides = {"pentagon": 5, "hexagon": 6, "octagon": 8}
        for w, k in n_sides.items():
            if w in topic.lower():
                cand[-1]["sides"] = k
        if domain == "math":
            add("worked_example", "use the parts with real numbers", "a formula is learned by using it")
    if domain == "programming":
        add("code_walkthrough", "short, correct code explained line by line, with its output",
            "it is a programming topic: learners need to see real code run")
        add("diagram", "trace what the code does, step by step", "a trace makes the order of execution visible",
            layout="flow")
        if level == "advanced":
            cand.append({"type": "code_walkthrough", "purpose": "a deeper example: an edge case or a faster way",
                         "why": "advanced learners need the tricky case, not only the basic one"})
    elif kind in ("place", "organisation") and not info.get("kb"):
        add("timeline", "when it began and the key moments since", f"{'an' if kind[0] in 'aeiou' else 'a'} {kind} has a history: a timeline shows it")
        add("diagram", "what it is known for", f"a hub shows the main features of the {kind}", layout="hub")
    elif kind == "person" or domain == "person":
        add("timeline", "the key events of their life in order (only years you are sure of)",
            "a life is a story in time: a timeline shows what happened when")
        add("diagram", "their main achievements or qualities", "a hub groups what they are known for", layout="hub")
    else:
        if "process" in shapes and len(arts) >= 2:
            add("illustration", "a picture of what goes in and what comes out",
                f"“{topic}” takes things in and gives things out, so arrows in and out explain it best",
                art=arts)
        if "cycle" in shapes:
            add("diagram", "the stages as a loop that returns to the start", "it repeats, so a cycle shows it",
                layout="cycle")
        if "parts" in shapes:
            add("diagram", "the main parts and what each one does", "it has parts, so a labelled hub shows them",
                layout="hub")
        if "time" in shapes and domain in ("history", "general", "earth"):
            add("timeline", "the events or stages in time order", "dates and stages are clearest on a timeline")
        if "calc" in shapes and (domain in ("math", "physics", "chemistry") or level != "beginner"):
            add("worked_example", "one problem solved with real numbers, step by step",
                "a rule is understood by using it on numbers")
        if "amount" in shapes:
            add("chart", "a bar chart of well-known amounts", "amounts are compared fastest as bars")
        if "compare" in shapes:
            add("table", "a table comparing them, one property per row",
                "a comparison is clearest as a table: the same property side by side")
        if "steps" in shapes or not cand:
            add("diagram", "the key steps in order", "a how-question is answered as steps with arrows", layout="flow")
        if level != "beginner" and domain in ("biology", "physics", "chemistry", "earth", "general"):
            add("diagram", "the mechanism, stage by stage (how and why it happens)",
                "beyond beginner level the lesson must explain how and why", layout="flow")
        if level == "advanced" and (re.search(r"\d|=|→", facts) or "equation" in text):
            add("worked_example", "the equation or the numbers behind it, worked step by step",
                "advanced learners should see the exact relationship")
        if info.get("intent") == "define" and len(cand) <= 1 and not shape:
            cand.insert(0, {"type": "diagram", "layout": "stack", "purpose": "what it is, in three key points",
                            "why": "a 'what is' question is answered with a clear definition first"})
        if len(arts) >= 2 and level == "beginner":
            add("illustration", "a labelled picture of the main things involved",
                "beginners understand a picture before words", art=arts)
        if domain == "math":
            add("worked_example", "a worked problem with real numbers", "maths is learned by doing")
    # level shapes the order: beginners start with a picture, advanced learners with the mechanism and numbers
    rank = {"beginner": ["shape", "illustration", "table", "diagram", "timeline", "code_walkthrough", "chart", "worked_example"],
            "intermediate": ["shape", "code_walkthrough", "table", "illustration", "diagram", "worked_example", "timeline", "chart"],
            "advanced": ["shape", "code_walkthrough", "table", "diagram", "worked_example", "chart", "timeline", "illustration"]}[level]
    r = lambda c: rank.index(c["type"]) if c["type"] in rank else 9
    cand = sorted(cand, key=r) if level != "beginner" else cand[:1] + sorted(cand[1:], key=r)
    fillers = [("diagram", "a closer look at how or why it happens", "builds on the previous scene", "flow"),
               ("diagram", "the key facts to remember", "a short list fixes the main points", "stack"),
               ("diagram", "where we see it in real life", "an everyday example makes it stick", "hub"),
               ("diagram", "a common mistake and the correct idea", "fixing a misconception deepens understanding", "flow")]
    for t, p, w, lay in fillers:
        if len(cand) >= n:
            break
        if not any(c["type"] == t and c.get("layout") == lay for c in cand) and t in allowed:
            cand.append({"type": t, "purpose": p, "why": w, "layout": lay})
    while len(cand) < n:                     # subjects without diagrams (e.g. maths) repeat their core type
        core = next((c for c in cand if c["type"] != "quiz"), None)
        if core is None:
            break
        cand.append(dict(core, purpose="another example, a little harder", why="practice builds on the first example"))
    scenes = cand[:n]
    out = [{"type": "title_card", "purpose": "the question this lesson answers", "why": "sets the goal"}] + scenes + \
          [{"type": "quiz", "purpose": "one question about something taught", "why": "checks understanding"}]
    return {"scenes": out, "types": sorted({s["type"] for s in out}), "arts": arts,
            "summary": " → ".join(_label(s) for s in out[1:-1])}


def _label(s):
    if s["type"] == "diagram":
        return {"flow": "steps", "cycle": "cycle", "hub": "labelled parts", "stack": "list"}.get(s.get("layout"), "diagram")
    return {"illustration": "picture", "shape": "shape", "table": "table", "code_walkthrough": "code", "worked_example": "worked example",
            "timeline": "timeline", "chart": "chart"}.get(s["type"], s["type"])


def prompt_lines(vp: dict) -> str:
    """The plan as instructions for the AI."""
    lines = ["Visual plan, chosen for this topic (write the scenes in this order, one per line below):"]
    for i, s in enumerate([x for x in vp["scenes"] if x["type"] != "title_card"], 1):
        t = s["type"] + (f", layout '{s['layout']}'" if s.get("layout") else "") + \
            (f", shape '{s['shape']}' with parts from: {', '.join(schema.SHAPES[s['shape']])}" if s.get("shape") else "") + \
            (f", sides {s['sides']}" if s.get("sides") else "")
        extra = f" Use these drawings (art): {', '.join(s['art'])} - pick roles main/in/out correctly." if s.get("art") else ""
        lines.append(f"  Scene {i} ({t}): {s['purpose']}.{extra}")
    lines.append("Every sentence must talk about what is on screen at that moment (set 'focus' to it).")
    return "\n".join(lines)


def check(vp: dict, scenes) -> dict:
    """Did the AI follow the plan, and does each picture make sense? -> {"followed", "planned", "notes"}"""
    want = [s["type"] for s in vp["scenes"][1:-1]]
    got = [s.type for s in scenes if s.type not in ("title_card", "quiz") and s.heading not in ("Recap", AGENDA_HEADING)]
    followed = sum(1 for t in want if t in got)
    notes = []
    for s in scenes:
        if s.type == "illustration":
            roles = [p.role for p in s.parts]
            if "in" not in roles and "out" not in roles and "part" not in roles:
                notes.append(f"'{s.heading}': the picture has no arrows or labelled parts")
            if sum(p.art == "dot" for p in s.parts) > len(s.parts) / 2:
                notes.append(f"'{s.heading}': most parts have no matching drawing")
    return {"followed": followed, "planned": len(want), "notes": notes}


AGENDA_HEADING = "What we will learn"
_SHORT = {"illustration": "What goes in and what comes out", "code_walkthrough": "Real code, line by line",
          "timeline": "The key events in time", "worked_example": "A worked example with numbers",
          "chart": "The numbers, as a chart", "table": "A comparison table"}
_SHORT_DIAGRAM = {"flow": "The steps, in order", "cycle": "The cycle, stage by stage", "hub": "The main parts",
                  "stack": "The key facts"}


def agenda_scene(vp: dict):
    """An instant 'what we will learn' scene built from the plan: plays while the AI is still writing."""
    items = []
    for s in vp["scenes"][1:-1]:
        lab = _SHORT_DIAGRAM.get(s.get("layout"), "A diagram") if s["type"] == "diagram" else _SHORT.get(s["type"], "")
        if lab and lab not in items:
            items.append(lab)
    items = items[:4] + ["A quick check"]
    if len(items) < 3:
        return None
    first, rest = items[0], items[1:-1]
    beats = [{"text": f"Here is our plan. First: {first.lower()}.", "focus": 0},
             {"text": (f"Then {', then '.join(r.lower() for r in rest)}, " if rest else "") + "and a quick check at the end.",
              "focus": len(items) - 1}]
    return schema.SceneAdapter.validate_python({"type": "diagram", "heading": AGENDA_HEADING, "layout": "stack",
                                                "items": items, "narration": beats})
