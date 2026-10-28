"""Lesson plan schema. The LLM must return JSON that passes `Lesson`.

Every scene has `narration`: a list of beats. A beat is one spoken sentence said while one thing
is in focus (a code line, a diagram box, a timeline event, a calculation step, a chart bar, a quiz
option). Beats are what keep voice and visuals in sync.

`llm_schema()` builds a *dynamic* schema for each request: only the scene types that suit the
subject (no code scenes for biology, a code scene required for programming), and exactly the
number of scenes and sentences that the chosen length needs. Ollama enforces it while generating.
"""
import copy
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter, field_validator, model_validator

Level = Literal["beginner", "intermediate", "advanced"]
LEVELS = ("beginner", "intermediate", "advanced")


class Beat(BaseModel):
    text: str = Field(min_length=2, max_length=400)
    focus: Optional[int] = Field(default=None, ge=0, le=20)  # line no. (1-based) or item index (0-based)


# drawings available in the player (frontend/player.js ART); the model may use only these names
ART = ("sun", "plant", "leaf", "tree", "water", "rain", "cloud", "sea", "mountain", "snow", "wind", "heat",
       "co2", "o2", "h2o", "glucose", "molecule", "atom", "beaker", "flask", "salt", "battery", "bulb",
       "resistor", "magnet", "ball", "rocket", "earth", "moon", "star", "heart", "lungs", "brain", "person",
       "blood", "cell", "dna", "virus", "food", "computer", "code", "gear", "clock", "book", "coin",
       "factory", "house", "flag", "dot")
ART_ALIASES = {"sunlight": "sun", "light": "sun", "plants": "plant", "leaves": "leaf", "roots": "plant",
               "carbon dioxide": "co2", "carbon_dioxide": "co2", "oxygen": "o2", "sugar": "glucose", "drop": "water",
               "droplet": "water", "ocean": "sea", "lake": "sea", "river": "water", "fire": "heat", "energy": "heat",
               "body": "person", "human": "person", "people": "person", "bacteria": "virus", "germ": "virus",
               "acid": "beaker", "base": "beaker", "chemical": "flask", "electricity": "battery", "lamp": "bulb",
               "planet": "earth", "money": "coin", "time": "clock", "city": "house", "country": "flag",
               "laptop": "computer", "program": "code", "machine": "gear", "vapour": "cloud", "vapor": "cloud",
               "ice": "snow", "water vapour": "cloud", "steam": "cloud", "food chain": "food", "lung": "lungs"}


class _Scene(BaseModel):
    heading: str = Field(min_length=2, max_length=90)
    narration: List[Beat] = Field(min_length=1, max_length=6)

    def _check_focus(self, n, base=0, what="item index"):
        for b in self.narration:
            if b.focus is not None and not (base <= b.focus < n + base):
                raise ValueError(f"focus {b.focus} must be a {what} {base}..{n - 1 + base}")


class TitleCard(_Scene):
    type: Literal["title_card"]
    subtitle: Optional[str] = Field(default=None, max_length=120)
    art: Optional[List[str]] = Field(default=None, max_length=3)     # drawings that open this topic

    @field_validator("art", mode="before")
    @classmethod
    def _arts(cls, v):
        if not v:
            return None
        out = []
        for a in v:
            a = str(a).strip().lower()
            a = ART_ALIASES.get(a, a)
            if a in ART and a != "dot" and a not in out:
                out.append(a)
        return out[:3] or None


class CodeWalkthrough(_Scene):
    type: Literal["code_walkthrough"]
    code: str = Field(min_length=1, max_length=700)
    code_language: str = "python"
    output: Optional[List[str]] = Field(default=None, max_length=8)  # what the program prints

    @model_validator(mode="after")
    def check(self):
        n = len(self.code.splitlines())
        if n > 14:
            raise ValueError("code too long: keep it under 14 lines")
        self._check_focus(n, base=1, what="code line number")
        return self


class Diagram(_Scene):
    type: Literal["diagram"]
    # flow = steps, cycle = repeating loop, stack = list/parts, hub = labelled illustration
    # (item 0 is the centre, the others are labelled parts around it)
    layout: Literal["flow", "cycle", "stack", "hub"] = "flow"
    items: List[str] = Field(min_length=2, max_length=7)
    icons: Optional[List[str]] = Field(default=None, max_length=7)        # one emoji per item
    edge_labels: Optional[List[str]] = Field(default=None, max_length=7)  # label on arrow i -> i+1

    @model_validator(mode="after")
    def check(self):
        n = len(self.items)
        if self.icons is not None:
            self.icons = [str(i)[:8] for i in self.icons[:n]]
        if self.edge_labels is not None:
            self.edge_labels = [str(e)[:28] for e in self.edge_labels[:n]]
        self._check_focus(n)
        for it in self.items:
            if len(it) > 40:
                raise ValueError("diagram item labels must be short (max 40 chars)")
        return self


class Event(BaseModel):
    label: str = Field(min_length=1, max_length=20)   # a year, a date or a stage name
    text: str = Field(min_length=2, max_length=70)


class Timeline(_Scene):
    type: Literal["timeline"]
    events: List[Event] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def check(self):
        self._check_focus(len(self.events))
        return self


class Chart(_Scene):
    type: Literal["chart"]
    chart_title: Optional[str] = Field(default=None, max_length=60)
    labels: List[str] = Field(min_length=2, max_length=8)
    values: List[float] = Field(min_length=2, max_length=8)
    unit: Optional[str] = Field(default=None, max_length=14)

    @model_validator(mode="after")
    def check(self):
        if len(self.labels) != len(self.values):
            raise ValueError("chart needs one value per label")
        self._check_focus(len(self.labels))
        return self


class WorkedExample(_Scene):
    type: Literal["worked_example"]
    problem: str = Field(min_length=3, max_length=160)
    steps: List[str] = Field(min_length=2, max_length=6)   # one line of working each
    answer: str = Field(min_length=1, max_length=70)

    @model_validator(mode="after")
    def check(self):
        self._check_focus(len(self.steps))
        return self


class Part(BaseModel):
    art: Literal[ART] = "dot"                          # which drawing
    label: str = Field(min_length=1, max_length=32)
    role: Literal["main", "in", "out", "part"] = "part"  # main = centre; in/out = arrows into/out of it
    via: Optional[str] = Field(default=None, max_length=24)  # words on the arrow ("through roots")

    @field_validator("art", mode="before")
    @classmethod
    def _art(cls, v):
        v = str(v or "dot").strip().lower()
        v = ART_ALIASES.get(v, v)
        return v if v in ART else "dot"


class Illustration(_Scene):
    """A topic picture: one main object in the centre, inputs flowing in, outputs flowing out,
    labelled parts around it. Each part appears when the narration focuses on it."""
    type: Literal["illustration"]
    parts: List[Part] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def check(self):
        mains = [i for i, p in enumerate(self.parts) if p.role == "main"]
        for i in mains[1:]:
            self.parts[i].role = "part"
        if not mains:
            self.parts[0].role = "main"
        self._check_focus(len(self.parts))
        return self


# geometry that the player draws exactly (and animates part by part)
SHAPES = {
    "circle": ("centre", "radius", "diameter", "circumference", "chord", "arc", "area"),
    "triangle": ("side_a", "side_b", "side_c", "base", "height", "angle_a", "angle_b", "angle_c", "area"),
    "right_triangle": ("base", "height", "hypotenuse", "right_angle", "angle", "area"),
    "square": ("side", "diagonal", "area", "perimeter", "right_angle"),
    "rectangle": ("length", "width", "diagonal", "area", "perimeter", "right_angle"),
    "polygon": ("side", "vertex", "angle", "centre", "area", "perimeter"),
    "angle": ("arm_1", "arm_2", "vertex", "angle"),
}
SHAPE_PARTS = tuple(sorted({p for v in SHAPES.values() for p in v}))
SHAPE_ALIASES = {"center": "centre", "middle": "centre", "perimeter_of_circle": "circumference", "radii": "radius",
                 "hyp": "hypotenuse", "side": "side", "sides": "side", "corner": "vertex", "point": "vertex",
                 "width": "width", "breadth": "width", "length": "length", "edge": "side", "outline": "perimeter"}


class ShapePart(BaseModel):
    part: str = Field(min_length=1, max_length=20)     # one of SHAPES[shape]
    label: str = Field(min_length=1, max_length=28)    # what is written beside it, e.g. "radius r = 7 cm"

    @field_validator("part", mode="before")
    @classmethod
    def _part(cls, v):
        v = str(v or "").strip().lower().replace(" ", "_").replace("-", "_")
        return SHAPE_ALIASES.get(v, v)


class Shape(_Scene):
    """An exact, animated geometric figure: each named part is drawn when the narration reaches it."""
    type: Literal["shape"]
    shape: Literal[tuple(SHAPES)] = "circle"
    sides: Optional[int] = Field(default=None, ge=3, le=10)          # polygon only
    degrees: Optional[float] = Field(default=None, gt=0, lt=360)      # angle only
    parts: List[ShapePart] = Field(min_length=1, max_length=6)

    @field_validator("shape", mode="before")
    @classmethod
    def _shape(cls, v):
        v = str(v or "circle").strip().lower().replace(" ", "_").replace("-", "_")
        v = {"round": "circle", "disc": "circle", "right_angled_triangle": "right_triangle", "square_shape": "square",
             "pentagon": "polygon", "hexagon": "polygon", "octagon": "polygon"}.get(v, v)
        return v if v in SHAPES else "circle"

    @model_validator(mode="after")
    def check(self):
        ok = [p for p in self.parts if p.part in SHAPES[self.shape]]
        if not ok:
            raise ValueError(f"shape parts must be from {SHAPES[self.shape]}")
        self.parts = ok
        self._check_focus(len(self.parts))
        return self


class Table(_Scene):
    """A comparison table; each row appears (and is highlighted) when the narration reaches it."""
    type: Literal["table"]
    columns: List[str] = Field(min_length=2, max_length=4)              # header cells
    rows: List[List[str]] = Field(min_length=2, max_length=6)            # one list of cells per row

    @model_validator(mode="after")
    def check(self):
        n = len(self.columns)
        self.columns = [str(c)[:24] for c in self.columns]
        fixed = []
        for r in self.rows:
            r = [str(c)[:40] for c in r][:n]
            if any(x.strip() for x in r):
                fixed.append(r + [""] * (n - len(r)))                    # pad short rows
        if len(fixed) < 2:
            raise ValueError("a table needs at least 2 rows")
        self.rows = fixed
        self._check_focus(len(self.rows))
        return self


class Quiz(_Scene):
    type: Literal["quiz"]
    question: str = Field(min_length=3, max_length=160)
    options: List[str] = Field(min_length=2, max_length=4)
    answer: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def check(self):
        if self.answer >= len(self.options):
            raise ValueError("answer index out of range")
        self._check_focus(len(self.options))
        return self


SCENE_CLASSES = {c.model_fields["type"].annotation.__args__[0]: c
                 for c in (TitleCard, CodeWalkthrough, Diagram, Timeline, Chart, WorkedExample, Illustration, Shape, Table,
                           Quiz)}
SCENE_TYPES = set(SCENE_CLASSES)

Scene = Annotated[Union[TitleCard, CodeWalkthrough, Diagram, Timeline, Chart, WorkedExample, Illustration, Shape,
                        Table, Quiz],
                  Field(discriminator="type")]
SceneAdapter = TypeAdapter(Scene)


class Lesson(BaseModel):
    title: str = Field(min_length=2, max_length=90)
    level: Level = "beginner"
    language: str = "en"
    domain: str = "general"
    scenes: List[Scene] = Field(min_length=3, max_length=8)
    prerequisites: List[str] = Field(default_factory=list, max_length=4)   # learn these first
    next_topics: List[str] = Field(default_factory=list, max_length=4)     # learn these next

    @model_validator(mode="after")
    def check(self):
        if self.scenes[0].type != "title_card":
            raise ValueError("first scene must be a title_card")
        self.prerequisites = [str(p)[:60] for p in self.prerequisites]
        self.next_topics = [str(p)[:60] for p in self.next_topics]
        return self


# ---------------------------------------------------------------- dynamic schema for the LLM

# Which scene types fit which subject. The first entry after title_card is the "core" type that
# must appear at least once (checked after generation).
DOMAIN_SCENES = {
    "programming": ["code_walkthrough", "diagram", "table", "quiz"],
    "biology":     ["diagram", "illustration", "timeline", "table", "quiz"],
    "physics":     ["diagram", "illustration", "worked_example", "chart", "shape", "table", "quiz"],
    "chemistry":   ["diagram", "illustration", "worked_example", "chart", "table", "quiz"],
    "math":        ["worked_example", "shape", "diagram", "chart", "table", "quiz"],
    "earth":       ["diagram", "illustration", "timeline", "chart", "table", "quiz"],
    "history":     ["timeline", "diagram", "table", "quiz"],
    "person":      ["timeline", "diagram", "table", "quiz"],
    "general":     ["diagram", "illustration", "timeline", "chart", "shape", "table", "quiz"],
}


def lesson_shape(seconds: int, level: str) -> dict:
    """How big the lesson must be for the chosen length.

    Timing model (measured on Kokoro): ~2.6 spoken English words per second, plus 1.0 s of
    lead-in and pause per scene and 0.25 s between sentences."""
    # at least 3 scenes after the title card at every length (title, 2+ teaching scenes, quiz)
    scenes = 4 if seconds <= 50 else 5 if seconds <= 70 else 6
    beats = 3 if level == "beginner" else 4          # sentences per content scene (max)
    if seconds <= 35:
        beats = 2                                    # 30 s: short scenes, so 3 of them still fit
    content = scenes - 1
    n_beats = 1 + content * beats
    speech = max(10.0, seconds - scenes * 1.0 - n_beats * 0.25)
    words = int(speech * 2.6)
    return {"scenes": scenes, "beats_min": 2, "beats_max": beats, "words": words,
            "words_per_beat": max(8, min(18, round(words / n_beats)))}


def llm_schema(domain: str, seconds: int, level: str, types=None, no_title=False) -> dict:
    """JSON schema passed to Ollama's `format`: the model can only write what fits.
    types: scene types chosen by the visual plan (a smaller schema is also faster to follow on a CPU)."""
    shape = lesson_shape(seconds, level)
    full = Lesson.model_json_schema()
    s = copy.deepcopy(full)
    allowed = ["title_card"] + DOMAIN_SCENES.get(domain, DOMAIN_SCENES["general"])
    if types:
        allowed = ["title_card"] + [t for t in allowed[1:] if t in types or t == "quiz"]
    if no_title:                      # Blu makes the title card itself (instantly); the AI writes less
        allowed = allowed[1:]
    if "illustration" not in allowed:
        s["$defs"].pop("Part", None)
    if "shape" not in allowed:
        s["$defs"].pop("ShapePart", None)
    elif "ShapePart" in s["$defs"]:
        s["$defs"]["ShapePart"]["properties"]["part"]["enum"] = list(SHAPE_PARTS)
    names = {"title_card": "TitleCard", "code_walkthrough": "CodeWalkthrough", "diagram": "Diagram",
             "timeline": "Timeline", "chart": "Chart", "worked_example": "WorkedExample", "illustration": "Illustration", "shape": "Shape", "table": "Table", "quiz": "Quiz"}
    defs = s["$defs"]
    # keep only the scene types allowed for this subject
    for t, n in names.items():
        if t not in allowed:
            defs.pop(n, None)
    items = s["properties"]["scenes"]["items"]
    items["oneOf"] = [{"$ref": f"#/$defs/{names[t]}"} for t in allowed]
    if "discriminator" in items:
        items["discriminator"]["mapping"] = {t: f"#/$defs/{names[t]}" for t in allowed}
    s["properties"]["scenes"]["minItems"] = max(3, shape["scenes"] - 1) - (1 if no_title else 0)
    s["properties"]["scenes"]["maxItems"] = shape["scenes"] - (1 if no_title else 0)
    # sentences per scene: enough to fill the chosen length
    for t in allowed:
        if names[t] not in defs:
            continue
        nar = defs[names[t]]["properties"]["narration"]
        if t == "title_card":
            nar["minItems"], nar["maxItems"] = 1, 2
        else:
            nar["minItems"], nar["maxItems"] = shape["beats_min"], shape["beats_max"]
    defs["Beat"]["properties"]["text"]["maxLength"] = 170
    # the model does not choose these; we set them
    for k in ("domain", "language", "level"):
        s["properties"].pop(k, None)
    s["required"] = ["title", "scenes", "prerequisites", "next_topics"]
    s["properties"]["prerequisites"]["maxItems"] = 3
    s["properties"]["next_topics"]["maxItems"] = 3
    if no_title:                      # the reading lists are not shown in the app: do not spend time on them
        for k in ("prerequisites", "next_topics"):
            s["properties"].pop(k, None)
        s["required"] = ["title", "scenes"]
    return s
