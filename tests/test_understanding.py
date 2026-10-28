"""Unit tests for the accuracy work: spelling, names, search scoring, levels, length, illustrations.

    py -3.11 -m unittest tests.test_understanding -v
"""
import json
import re
import unittest
from pathlib import Path

from backend import knowledge, pipeline, planner, retrieval, schema, spelling, topic_nlp

ROOT = Path(__file__).resolve().parent.parent
A = topic_nlp.analyze


class Spelling(unittest.TestCase):
    def test_spec_examples(self):
        self.assertEqual(A("photosysthesis")["kb"], "photosynthesis")
        a = A("phito systhse")                     # broken into two words, too far to rewrite silently:
        self.assertEqual(a["status"], "unclear")   # the learner is asked "Did you mean photosynthesis?"
        self.assertEqual(a["suggestions"], ["photosynthesis"])
        self.assertEqual(A(a["suggestions"][0])["kb"], "photosynthesis")
        self.assertEqual(A("photosynthesis explain simple")["kb"], "photosynthesis")
        a = A("how pyton loop work")
        self.assertIn(["pyton", "python"], a["fixes"])
        self.assertEqual(a["kb"], "python_loop")
        a = A("binary serch algoritm")
        self.assertEqual(a["topic"], "binary search algorithm")
        self.assertEqual(a["kb"], "binary_search")

    def test_spaces_and_swapped_letters(self):
        self.assertEqual(A("photo synthesis")["topic"], "photosynthesis")
        self.assertEqual(A("binarysearch")["topic"], "binary search")
        self.assertEqual(A("pyhsics of blak holes")["topic"], "physics of black holes")

    def test_correct_words_and_names_untouched(self):
        for q in ["the heart pumps blood how", "sachin tendulkar", "virat kohli", "Virat Kohli", "rahul dravid",
                  "what is DNA", "Ohm's law", "Cholas dynasty", "photo editing tips"]:
            self.assertEqual(A(q)["fixes"], [], q)
        self.assertEqual(A("sachin tendulkar")["kind"], "person")
        self.assertEqual(A("virat kohli")["kind"], "person")

    def test_uncertain_is_a_suggestion_not_a_rewrite(self):
        st = spelling._load(set(topic_nlp._vocab()))
        self.assertEqual(spelling.fix_word("virat", st, set())[1], "suggest")     # not "high": never rewritten
        out, fixes, sugg = spelling.correct(["phito", "sythse", "wxyz"], set(topic_nlp._vocab()))
        self.assertTrue(fixes or sugg)

    def test_works_without_symspellpy(self):
        saved = spelling.symspellpy
        try:
            spelling.symspellpy = None
            spelling._state.clear()
            self.assertEqual(A("photosynthsis")["kb"], "photosynthesis")
        finally:
            spelling.symspellpy = saved
            spelling._state.clear()


class Search(unittest.TestCase):
    def test_meaning_not_just_words(self):
        self.assertEqual(A("how green plants make food using sunlight")["kb"], "photosynthesis")
        self.assertEqual(A("why does it rain")["kb"], "water_cycle")
        self.assertEqual(A("how to find the longest side of a triangle")["kb"], "pythagoras")

    def test_no_false_matches(self):
        a = A("how does a car engine work")            # "car" appears in a Newton example only
        self.assertIsNone(a["kb"])
        self.assertEqual(a["related"], "newtons_laws")   # background for the AI, not the lesson
        self.assertEqual(A("water cycle")["kb"], "water_cycle")
        self.assertEqual(A("python works")["kb"], "python_basics")
        self.assertEqual(A("how pyton loop work")["kb"], "python_loop")

    def test_person_is_not_a_topic_lesson(self):
        a = A("Mahatma Gandhi")
        self.assertIsNone(a["kb"])
        self.assertEqual(a["related"], "indian_independence")
        self.assertEqual(a["kind"], "person")

    def test_retries_are_bounded_and_different(self):
        r = retrieval.retrieve("Cholas dynasty", ["cholas", "dynasty"], ["dynasty"], ["dynasty"])
        qs = [frozenset(retrieval.tokens(x["query"])) for x in r["attempts"]]
        self.assertLessEqual(len(qs), 3)
        self.assertEqual(len(qs), len(set(qs)))
        self.assertFalse(any("dynasty dynasty" in x["query"] for x in r["attempts"]))

    def test_weak_match_never_replaces_the_lesson(self):
        self.assertGreater(pipeline.FALLBACK_MIN_SCORE, retrieval.THRESHOLD)


class Levels(unittest.TestCase):
    def test_three_levels_differ(self):
        for tid in ("python_basics", "photosynthesis", "water_cycle", "ohms_law"):
            heads = [tuple(s.heading for s in knowledge.assemble(tid, lv, 60).scenes[1:])
                     for lv in ("beginner", "intermediate", "advanced")]
            self.assertEqual(len(set(heads)), 3, tid)

    def test_python_levels_go_deeper(self):
        code = {lv: " ".join(s.code for s in knowledge.assemble("python_basics", lv, 60).scenes
                             if s.type == "code_walkthrough") for lv in ("beginner", "intermediate", "advanced")}
        self.assertIn("print", code["beginner"])
        self.assertIn("def ", code["intermediate"])
        self.assertIn("yield", code["advanced"])

    def test_prompt_level_guide(self):
        info = A("photosynthesis")
        for lv in ("beginner", "intermediate", "advanced"):
            self.assertIn(lv.upper(), planner.build_prompt(info, lv, 60))


class LengthAndScenes(unittest.TestCase):
    def test_three_scenes_after_title_at_every_length(self):
        for s in (30, 45, 60, 75, 90):
            self.assertGreaterEqual(schema.lesson_shape(s, "beginner")["scenes"] - 1, 3, s)
        for tid in knowledge.all_topics():
            for lv in ("beginner", "intermediate", "advanced"):
                for s in (30, 45, 60, 90):
                    L = knowledge.assemble(tid, lv, s)
                    self.assertGreaterEqual(sum(x.type != "title_card" for x in L.scenes), 3, (tid, lv, s))

    def test_word_budget_grows_with_length(self):
        w = [schema.lesson_shape(s, "beginner")["words"] for s in (30, 45, 60, 90)]
        self.assertEqual(w, sorted(w))
        self.assertLess(w[0], 75)                      # 30 s must stay short

    def test_output_checks(self):
        scenes = [{"type": "title_card", "start": 0, "end": 5}, {"type": "diagram", "start": 5, "end": 15},
                  {"type": "diagram", "start": 15, "end": 24}, {"type": "quiz", "start": 24, "end": 31}]
        c = pipeline.output_checks({"scenes": scenes, "duration": 31}, 30)
        self.assertTrue(all(v["ok"] for v in c.values()), c)
        c = pipeline.output_checks({"scenes": scenes[:3], "duration": 45}, 30)
        self.assertFalse(c["scenes"]["ok"])
        self.assertFalse(c["duration"]["ok"])


class Prompt(unittest.TestCase):
    def test_structured_context(self):
        info = A("photosynthsis explain")
        p = planner.build_prompt(info, "beginner", 60)
        self.assertIn("The learner typed", p)
        self.assertIn("Checked facts (source: offline notes", p)
        self.assertIn("Key terms", p)
        p = planner.build_prompt(dict(A("how does a car engine work")), "beginner", 60)
        self.assertIn("Possibly related checked notes", p)
        p = planner.build_prompt(dict(info, feedback=["scene 'x' was off topic"]), "beginner", 60)
        self.assertIn("previous answer was not usable", p)


class Illustration(unittest.TestCase):
    def test_schema_repairs_art_and_main(self):
        sc = schema.SceneAdapter.validate_python({
            "type": "illustration", "heading": "Step 1: Test",
            "parts": [{"art": "Sunlight", "label": "Sun", "role": "in"}, {"art": "unicorn", "label": "Plant"},
                      {"art": "Carbon Dioxide", "label": "CO2", "role": "main"}, {"art": "o2", "label": "O", "role": "main"}],
            "narration": [{"text": "Hello there.", "focus": 3}]})
        self.assertEqual([p.art for p in sc.parts], ["sun", "dot", "co2", "o2"])
        self.assertEqual([p.role for p in sc.parts].count("main"), 1)
        with self.assertRaises(Exception):
            schema.SceneAdapter.validate_python({"type": "illustration", "heading": "Bad one",
                                                 "parts": [{"art": "sun", "label": "a"}, {"art": "sun", "label": "b"}],
                                                 "narration": [{"text": "Hello there.", "focus": 5}]})

    def test_player_has_every_drawing(self):
        js = (ROOT / "frontend" / "player.js").read_text(encoding="utf-8")
        block = js[js.index("const ART = {"):js.index("// natural places")]
        names = set(re.findall(r"^  (\w+): g\(", block, re.M))
        self.assertEqual(names, set(schema.ART))

    def test_photosynthesis_picture_is_complete(self):
        sc = [s for s in knowledge.assemble("photosynthesis", "beginner", 60).scenes if s.type == "illustration"][0]
        arts = {p.art: p.role for p in sc.parts}
        self.assertEqual(arts["plant"], "main")
        for need in ("sun", "water", "co2"):
            self.assertEqual(arts.get(need), "in", need)       # carbon dioxide is never left out
        for need in ("glucose", "o2"):
            self.assertEqual(arts.get(need), "out", need)

    def test_illustration_allowed_for_science_not_code(self):
        self.assertIn("illustration", schema.DOMAIN_SCENES["biology"])
        self.assertNotIn("illustration", schema.DOMAIN_SCENES["programming"])
        s = schema.llm_schema("biology", 60, "beginner")
        self.assertIn("Illustration", s["$defs"])
        self.assertIn("co2", s["$defs"]["Part"]["properties"]["art"]["enum"])

    def test_repair_keeps_illustration(self):
        sc = planner.repair_scene({"type": "illustration", "heading": "Step 1: x",
                                   "parts": [{"art": "sun", "label": "Sun", "role": "weird"}, {"label": "Leaf"}, {"label": ""}],
                                   "narration": [{"text": "The sun shines.", "focus": 9}]}, "T", {"illustration"})
        self.assertIsNotNone(sc)
        self.assertEqual(len(sc.parts), 2)

    def test_knowledge_files_valid(self):
        for f in (ROOT / "backend" / "knowledge").glob("*.json"):
            kb = json.loads(f.read_text(encoding="utf-8"))
            for lv in ("beginner", "intermediate", "advanced"):
                knowledge.assemble(kb["id"], lv, 60)          # raises if any scene is invalid


if __name__ == "__main__":
    unittest.main()


class VisualReasoning(unittest.TestCase):
    from backend import visual_plan as V

    def plan(self, q, lv="beginner", sec=60):
        return self.V.plan(A(q), lv, sec)

    def types(self, vp):
        return [(s["type"], s.get("layout")) for s in vp["scenes"][1:-1]]

    def test_plan_matches_topic_shape(self):
        vp = self.plan("photosynthesis")
        self.assertEqual(vp["scenes"][1]["type"], "illustration")          # a process: picture with in/out arrows
        for a in ("plant", "sun", "water", "co2", "glucose", "o2"):
            self.assertIn(a, vp["scenes"][1]["art"], a)
        self.assertIn(("diagram", "cycle"), self.types(self.plan("water cycle", "advanced")))
        self.assertIn(("diagram", "hub"), self.types(self.plan("How does the human heart work?", "intermediate")))
        self.assertEqual(self.types(self.plan("Virat Kohli"))[0][0], "timeline")
        self.assertEqual(self.types(self.plan("Taj Mahal"))[0][0], "timeline")
        self.assertEqual(self.types(self.plan("python works"))[0][0], "code_walkthrough")
        self.assertEqual(self.types(self.plan("Pythagorean theorem", sec=30))[0][0], "shape")    # draw the triangle first
        self.assertEqual(self.types(self.plan("what is gravity"))[0], ("diagram", "stack"))

    def test_facts_do_not_change_the_shape(self):
        # a checked fact about the Calvin *cycle* must not make photosynthesis a cycle diagram
        self.assertNotIn(("diagram", "cycle"), self.types(self.plan("photosynthesis", "intermediate")))

    def test_level_changes_the_plan(self):
        b, a = self.plan("photosynthesis", "beginner"), self.plan("photosynthesis", "advanced")
        self.assertEqual(b["scenes"][1]["type"], "illustration")            # beginners: picture first
        self.assertNotEqual(a["scenes"][1]["type"], "illustration")         # advanced: mechanism first
        self.assertEqual([t for t, _ in self.types(self.plan("python works", "advanced"))].count("code_walkthrough"), 2)

    def test_plan_fits_the_length(self):
        for sec in (30, 45, 60, 90):
            vp = self.plan("photosynthesis", "beginner", sec)
            self.assertEqual(len(vp["scenes"]), schema.lesson_shape(sec, "beginner")["scenes"], sec)
            self.assertEqual(vp["scenes"][0]["type"], "title_card")
            self.assertEqual(vp["scenes"][-1]["type"], "quiz")

    def test_plan_reaches_prompt_and_schema(self):
        info = A("photosynthesis")
        vp = self.V.plan(info, "beginner", 60)
        p = planner.build_prompt(dict(info, visual=vp), "beginner", 60)
        self.assertIn("Visual plan", p)
        self.assertIn("co2", p)
        refs = [x["$ref"] for x in schema.llm_schema(info["domain"], 60, "beginner", vp["types"])
                ["properties"]["scenes"]["items"]["oneOf"]]
        self.assertNotIn("#/$defs/Timeline", refs)                          # only the planned types

    def test_check_reports_following(self):
        vp = self.plan("photosynthesis")
        scenes = knowledge.assemble("photosynthesis", "beginner", 60).scenes
        c = self.V.check(vp, scenes)
        self.assertGreaterEqual(c["followed"], 1)
        self.assertEqual(c["notes"], [])


class Speed(unittest.TestCase):
    def test_fast_model_preferred_when_installed(self):
        from unittest import mock
        from backend import config

        class R:
            def __init__(s, names): s.n = names
            def raise_for_status(s): pass
            def json(s): return {"models": [{"name": n} for n in s.n]}
        with mock.patch("requests.get", return_value=R(["phi4-mini:latest", "qwen2.5:1.5b"])), \
                mock.patch.object(config, "SPEED_MODE", "fast"):
            self.assertEqual(planner.pick_model(), "qwen2.5:1.5b")
        with mock.patch("requests.get", return_value=R(["phi4-mini:latest"])), mock.patch.object(config, "SPEED_MODE", "fast"):
            self.assertEqual(planner.pick_model(), "phi4-mini:latest")          # not installed: falls back
        with mock.patch("requests.get", return_value=R(["phi4-mini:latest", "qwen2.5:1.5b"])), \
                mock.patch.object(config, "SPEED_MODE", "quality"):
            self.assertEqual(planner.pick_model(), "phi4-mini:latest")

    def test_ai_writes_less(self):
        s = schema.llm_schema("biology", 60, "beginner", no_title=True)
        refs = [x["$ref"] for x in s["properties"]["scenes"]["items"]["oneOf"]]
        self.assertNotIn("#/$defs/TitleCard", refs)
        self.assertNotIn("prerequisites", s["properties"])

    def test_agenda_scene_from_plan(self):
        from backend import visual_plan
        sc = visual_plan.agenda_scene(visual_plan.plan(A("photosynthesis"), "beginner", 60))
        self.assertEqual(sc.heading, visual_plan.AGENDA_HEADING)
        self.assertIn("What goes in and what comes out", sc.items)


class Shapes(unittest.TestCase):
    from backend import visual_plan as V

    def test_shape_chosen_for_geometry(self):
        for q, want in [("circle", "circle"), ("area of a triangle", "triangle"), ("Pythagorean theorem", "right_triangle"),
                        ("rectangle perimeter", "rectangle"), ("hexagon", "polygon"), ("types of angles", "angle")]:
            vp = self.V.plan(A(q), "beginner", 60)
            sh = [s for s in vp["scenes"] if s["type"] == "shape"]
            self.assertTrue(sh, q)
            self.assertEqual(sh[0]["shape"], want, q)
        vp = self.V.plan(A("hexagon"), "beginner", 60)
        self.assertEqual([s for s in vp["scenes"] if s["type"] == "shape"][0].get("sides"), 6)
        self.assertFalse(any(s["type"] == "shape" for s in self.V.plan(A("photosynthesis"))["scenes"]))

    def test_shape_schema_repairs(self):
        sc = schema.SceneAdapter.validate_python({
            "type": "shape", "heading": "Step 1: A circle", "shape": "Round",
            "parts": [{"part": "center", "label": "centre O"}, {"part": "Radius", "label": "r"}, {"part": "wing", "label": "x"}],
            "narration": [{"text": "The centre.", "focus": 0}, {"text": "The radius.", "focus": 1}]})
        self.assertEqual((sc.shape, [p.part for p in sc.parts]), ("circle", ["centre", "radius"]))

    def test_player_draws_every_shape(self):
        js = (ROOT / "frontend" / "player.js").read_text(encoding="utf-8")
        for name in schema.SHAPES:
            if name != "angle":                                   # angle is the final else-branch
                self.assertIn(f'"{name}"', js, name)

    def test_circle_lesson(self):
        for lv in ("beginner", "intermediate", "advanced"):
            L = knowledge.assemble("circle", lv, 60)
            self.assertTrue(any(s.type == "shape" for s in L.scenes), lv)
        self.assertEqual(A("what is a circle")["kb"], "circle")
        for q in ("what is a square root", "area of a square"):      # no false matches on general words
            self.assertNotIn(A(q)["kb"], ("pythagoras", "circle"), q)

    def test_title_card_has_topic_drawings(self):
        from backend import pipeline
        info = dict(A("photosynthesis"), visual=self.V.plan(A("photosynthesis")))
        self.assertTrue(pipeline._title_art(info))
        self.assertEqual(pipeline._title_art({"domain": "programming"}), ["code", "computer"])


class CompactFormat(unittest.TestCase):
    def test_compact_is_much_smaller(self):
        import json as _j
        from backend import visual_plan as V
        info = A("How do vaccines work?")
        vp = V.plan(info, "beginner", 60)
        info = dict(info, visual=vp)
        full = len(_j.dumps(schema.llm_schema(info["domain"], 60, "beginner", vp["types"], no_title=True)))
        small = len(_j.dumps(planner.compact_schema(vp, 60, "beginner")))
        self.assertLess(small, full / 2)
        self.assertLess(len(planner.build_prompt(info, "beginner", 60, compact=True)),
                        len(planner.build_prompt(info, "beginner", 60)) + 200)

    def test_expand_every_planned_type(self):
        cases = [
            ({"h": "Steps", "l": ["a b", "c d"], "s": ["One two three.", "Four five six."]}, {"type": "diagram", "layout": "flow"}),
            ({"h": "Plant", "l": ["main: Green plant", "in: Sunlight", "out: Oxygen"],
              "s": ["A plant.", "Sunlight in.", "Oxygen out."]}, {"type": "illustration", "art": ["plant", "sun", "o2"]}),
            ({"h": "Parts", "l": ["centre: centre O", "radius: radius r"], "s": ["Centre.", "Radius."]},
             {"type": "shape", "shape": "circle"}),
            ({"h": "Dates", "l": ["1947: India becomes free", "1950: Constitution starts"], "s": ["In 1947.", "In 1950."]},
             {"type": "timeline"}),
            ({"h": "Water", "l": ["Oceans: 97", "Ice: 2"], "u": "%", "s": ["Oceans hold most.", "Ice holds some."]},
             {"type": "chart"}),
            ({"h": "Solve", "p": "2 + 3?", "l": ["2 + 3 = 5"], "ans": "5", "s": ["Add them.", "It is five."]},
             {"type": "worked_example"}),
            ({"h": "Code", "c": "for i in range(2):\n    print(i)", "out": ["0", "1"], "s": ["Line one.", "Line two."]},
             {"type": "code_walkthrough"}),
            ({"h": "Quick check", "q": "Which?", "o": ["A", "B", "C"], "a": 1, "s": ["Quick check.", "B."]}, {"type": "quiz"}),
        ]
        for c, ps in cases:
            sc = planner.repair_scene(planner.expand_compact(c, ps, 1), "T", {ps["type"]})
            self.assertIsNotNone(sc, ps["type"])
            self.assertEqual(sc.type, ps["type"])
        sc = planner.repair_scene(planner.expand_compact(cases[1][0], cases[1][1], 1), "T", {"illustration"})
        self.assertEqual([(p.art, p.role) for p in sc.parts], [("plant", "main"), ("sun", "in"), ("o2", "out")])
        q = planner.repair_scene(planner.expand_compact(cases[-1][0], cases[-1][1], 1), "T", {"quiz"})
        self.assertEqual(q.narration[-1].focus, 1)                       # the last sentence reveals the answer


class OnTopicCheck(unittest.TestCase):
    def test_different_words_ok_other_subject_rejected(self):
        from backend import pipeline, retrieval
        from tests.fake_ollama import FRENCH
        info = A("French Revolution")
        ctx = set(retrieval.tokens(info["topic"] + " " + " ".join(info["key_terms"])))
        for x in FRENCH["scenes"][1:]:                           # "1789: the Bastille is stormed" never says "French"
            ok, why = pipeline.validate_scene(schema.SceneAdapter.validate_python(x), ctx, [], lenient=True)
            self.assertTrue(ok, why)
        for sc in knowledge.assemble("python_loop", "beginner", 60).scenes[1:]:
            ok, why = pipeline.validate_scene(sc, ctx, [], lenient=True)
            self.assertFalse(ok)
            self.assertIn("Python", why)
        sc = knowledge.assemble("python_loop", "beginner", 60).scenes[1]
        self.assertFalse(pipeline.validate_scene(sc, ctx, [])[0])           # strict mode (title off topic)


class LazyModel(unittest.TestCase):
    def test_answer_without_labels_still_makes_scenes(self):
        from backend import visual_plan as V
        vp = V.plan(A("Explain the box model"), "beginner", 60)
        planned = vp["scenes"][1:]
        lazy = [{"h": "What is the box model", "s": ["Every element on a web page is a box.", "It has content and padding."]},
                {"h": "The layers", "s": ["Content holds the text.", "Padding adds space inside."]}]
        for k, c in enumerate(lazy):
            sc = planner.repair_scene(planner.expand_compact(c, planned[k], k + 1), "t", {"diagram", "quiz"})
            self.assertIsNotNone(sc)
            self.assertGreaterEqual(len(sc.items), 2)

    def test_missing_special_data_becomes_a_diagram(self):
        for ps in ({"type": "code_walkthrough"}, {"type": "timeline"}, {"type": "chart"}, {"type": "shape", "shape": "circle"}):
            sc = planner.repair_scene(planner.expand_compact({"h": "X", "l": ["alpha beta", "gamma delta"],
                                                              "s": ["One two.", "Three four."]}, ps, 1), "t", {"diagram"})
            self.assertEqual(sc.type, "diagram", ps)

    def test_schema_requires_labels_and_quiz_fields(self):
        from backend import visual_plan as V
        sch = planner.compact_schema(V.plan(A("photosynthesis")), 60, "beginner")
        teach, quiz = sch["properties"]["scenes"]["items"]["oneOf"]
        self.assertIn("l", teach["required"])
        self.assertTrue({"q", "o", "a"} <= set(quiz["required"]))


class FastFirstSlide(unittest.TestCase):
    def test_search_model_kept_loaded_and_one_call_per_topic(self):
        from unittest import mock
        calls = []

        class R:
            def __init__(s, body): s.body = body
            def raise_for_status(s): pass
            def json(s): return {"embeddings": [[1.0, 0.0]] * len(s.body["input"])}

        def post(url, json=None, timeout=None):
            calls.append(json)
            return R(json)
        with mock.patch.object(retrieval, "_embed_available", return_value=True), \
                mock.patch.object(retrieval, "_topic_vectors", return_value={"photosynthesis": [1.0, 0.0]}), \
                mock.patch("requests.post", side_effect=post):
            retrieval.retrieve("zzqx unknown words here", ["zzqx", "unknown"], ["zzqx"], ["here"])
        self.assertEqual(len(calls), 1)                          # all (up to 3) tries embedded in ONE call
        self.assertEqual(calls[0]["keep_alive"], -1)             # the search model stays loaded
        self.assertGreaterEqual(len(calls[0]["input"]), 2)

    def test_player_checks_for_new_slides_often(self):
        html = (ROOT / "frontend" / "player.html").read_text(encoding="utf-8")
        self.assertIn("tl.complete ? 1000 : 300", html)

    def test_first_scene_is_asked_short(self):
        from backend import visual_plan as V
        info = A("How do vaccines work?")
        p = planner.build_prompt(dict(info, visual=V.plan(info, "beginner", 60)), "beginner", 60, compact=True)
        self.assertEqual(p.count("Keep THIS first scene short"), 1)


class Tables(unittest.TestCase):
    def test_table_schema_pads_and_checks(self):
        sc = schema.SceneAdapter.validate_python({
            "type": "table", "heading": "Step 1: Compare", "columns": ["Property", "Acid", "Base"],
            "rows": [["Taste", "Sour"], ["pH", "Below 7", "Above 7", "extra"]],
            "narration": [{"text": "Taste.", "focus": 0}, {"text": "pH.", "focus": 1}]})
        self.assertEqual(sc.rows, [["Taste", "Sour", ""], ["pH", "Below 7", "Above 7"]])
        with self.assertRaises(Exception):
            schema.SceneAdapter.validate_python({"type": "table", "heading": "x y", "columns": ["a", "b"],
                                                 "rows": [["1", "2"]], "narration": [{"text": "one."}]})

    def test_compact_table_and_fallback(self):
        c = {"h": "Acids vs bases", "l": ["Property | Acid | Base", "Taste | Sour | Bitter", "pH | Below 7 | Above 7"],
             "s": ["Taste.", "pH."]}
        sc = planner.repair_scene(planner.expand_compact(c, {"type": "table"}, 1), "t", {"table"})
        self.assertEqual((sc.type, sc.columns), ("table", ["Property", "Acid", "Base"]))
        sc = planner.repair_scene(planner.expand_compact({"h": "X", "l": ["alpha beta", "gamma delta"], "s": ["A.", "B."]},
                                                         {"type": "table"}, 1), "t", {"diagram"})
        self.assertEqual(sc.type, "diagram")                    # no real rows: a list, not a broken table

    def test_comparisons_get_a_table(self):
        from backend import visual_plan as V
        for q in ("difference between acids and bases", "compare mitosis and meiosis", "photosynthesis vs respiration"):
            self.assertEqual(V.plan(A(q), "intermediate", 60)["scenes"][1]["type"], "table", q)

    def test_player_and_translation_know_tables(self):
        js = (ROOT / "frontend" / "player.js").read_text(encoding="utf-8")
        self.assertIn("table(root, sc)", js)
        from backend import translate
        sc = knowledge.assemble("acids_bases", "intermediate", 60).scenes
        tab = [s for s in sc if s.type == "table"][0]
        texts = [translate._get(o, f, i) for o, f, i in translate._slots(tab)]
        self.assertIn("Sour", texts)
        self.assertIn("Property", texts)

    def test_no_duplicate_scenes_in_checked_lessons(self):
        for tid in knowledge.all_topics():
            for lv in ("beginner", "intermediate", "advanced"):
                for sec in (30, 45, 60, 90):
                    hs = [re.sub(r"^Step \d+:\s*(A closer look:\s*)?", "", s.heading)
                          for s in knowledge.assemble(tid, lv, sec).scenes]
                    self.assertEqual(len(hs), len(set(hs)), (tid, lv, sec))
