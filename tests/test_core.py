"""Unit tests for the critical logic (no network, no models). Run:  py -3.11 -m unittest tests.test_core -v"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import documents, exam, exporter, knowledge, pipeline, planner, retrieval, schema, topic_nlp  # noqa: E402


class NLP(unittest.TestCase):
    def test_academic_topic(self):
        a = topic_nlp.analyze("Photosynthesis")
        self.assertEqual((a["status"], a["domain"], a["kb"]), ("ok", "biology", "photosynthesis"))

    def test_named_entity_person(self):
        a = topic_nlp.analyze("Virat Kohli")
        self.assertEqual((a["status"], a["kind"], a["domain"]), ("ok", "person", "person"))
        self.assertEqual(a["entities"][0]["text"], "Virat Kohli")
        self.assertFalse(a["grounded"])

    def test_broad_topic_gets_choices(self):
        a = topic_nlp.analyze("Artificial Intelligence")
        self.assertEqual(a["status"], "broad")
        self.assertGreaterEqual(len(a["suggestions"]), 3)

    def test_random_string_is_invalid(self):
        self.assertEqual(topic_nlp.analyze("asdf qwer zxcv")["status"], "invalid")

    def test_random_string_with_keyword_is_a_suggestion(self):
        a = topic_nlp.analyze("xkcd photosynthesis qwrtp")
        self.assertEqual(a["status"], "unclear")
        self.assertIn("photosynthesis", " ".join(a["suggestions"]).lower())

    def test_misspelling_fixed(self):
        a = topic_nlp.analyze("photosynthsis")
        self.assertEqual(a["topic"], "photosynthesis")
        self.assertEqual(a["kb"], "photosynthesis")

    def test_names_are_never_spell_corrected(self):
        self.assertEqual(topic_nlp.analyze("Kalpana Chawla")["topic"], "Kalpana Chawla")

    def test_no_offline_knowledge(self):
        a = topic_nlp.analyze("French Revolution")
        self.assertIsNone(a["kb"])
        self.assertEqual(a["facts"], [])

    def test_basic_fallback_when_nlp_fails(self):
        a = topic_nlp.basic("  Virat   Kohli ")
        self.assertEqual((a["topic"], a["kb"], a["status"]), ("Virat Kohli", None, "ok"))


class Retrieval(unittest.TestCase):
    def test_different_words_same_topic(self):
        self.assertEqual(retrieval.retrieve("how plants make food")["topic"], "photosynthesis")
        self.assertEqual(retrieval.retrieve("how to find the longest side of a triangle")["topic"], "pythagoras")

    def test_irrelevant_returns_none(self):
        r = retrieval.retrieve("French Revolution", ["french", "revolution"])
        self.assertIsNone(r["topic"])

    def test_bounded_retry_with_reformulation(self):
        q = "explain zorbix flumpy quantum gadgets and the leaf pigment chlorophyll"
        r = retrieval.retrieve(q, ["chlorophyll", "leaf"])
        self.assertLessEqual(len(r["attempts"]), 3)
        self.assertGreaterEqual(len(r["attempts"]), 2)        # the first query failed, a reformulation succeeded
        self.assertEqual(r["topic"], "photosynthesis")


class Schema(unittest.TestCase):
    def test_knowledge_lessons_valid_for_every_level_and_length(self):
        for tid in knowledge.all_topics():
            for lv in schema.LEVELS:
                for sec in (30, 45, 60, 90):
                    L = knowledge.assemble(tid, lv, sec)
                    self.assertEqual(L.scenes[0].type, "title_card")

    def test_dynamic_schema_follows_subject_and_length(self):
        s = schema.llm_schema("biology", 90, "beginner")
        refs = {x["$ref"] for x in s["properties"]["scenes"]["items"]["oneOf"]}
        self.assertNotIn("#/$defs/CodeWalkthrough", refs)
        self.assertEqual(s["properties"]["scenes"]["maxItems"], 6)
        p = schema.llm_schema("programming", 30, "beginner")
        self.assertIn("#/$defs/CodeWalkthrough", {x["$ref"] for x in p["properties"]["scenes"]["items"]["oneOf"]})
        self.assertEqual(p["properties"]["scenes"]["maxItems"], 4)   # 3+ scenes after the title, even at 30 s


class Planner(unittest.TestCase):
    def test_stream_parser_handles_any_chunking(self):
        L = knowledge.assemble("human_heart", "advanced", 90).model_dump()
        raw = json.dumps({"title": L["title"], "scenes": L["scenes"], "prerequisites": ["a"], "next_topics": ["b"]})
        for step in (1, 3, 17):
            p = planner.SceneStream()
            ev = []
            for i in range(0, len(raw), step):
                ev += p.feed(raw[i:i + step])
            self.assertEqual(sum(e[0] == "scene" for e in ev), len(L["scenes"]))

    def test_repair_quiz_prefixes_and_bad_answers(self):
        q = planner.repair_scene({"type": "quiz", "heading": "Q", "question": "Which?", "options": ["A) x", "B) y"],
                                  "answer": 1, "narration": ["Quick check.", "y"]})
        self.assertEqual(q.options, ["x", "y"])
        self.assertIsNone(planner.repair_scene({"type": "quiz", "heading": "Q", "question": "Which?",
                                                "options": ["x", "y"], "answer": 7, "narration": ["a b"]}))

    def test_code_not_allowed_for_biology(self):
        sc = {"type": "code_walkthrough", "heading": "x", "code": "a=1", "narration": ["sunlight = True"]}
        self.assertIsNone(planner.repair_scene(sc, allowed={"title_card", "diagram", "timeline", "quiz"}))


class SmartValidation(unittest.TestCase):
    def test_off_topic_scene_rejected(self):
        ctx = set(retrieval.tokens("French Revolution france king"))
        sc = knowledge.assemble("python_loop", "beginner", 60).scenes[1]
        ok, why = pipeline.validate_scene(sc, ctx, [])
        self.assertFalse(ok)
        self.assertIn("off topic", why)

    def test_on_topic_scene_accepted(self):
        info = topic_nlp.analyze("photosynthesis")
        ctx = set(retrieval.tokens(info["topic"] + " " + " ".join(info["facts"])))
        sc = knowledge.assemble("photosynthesis", "beginner", 60).scenes[1]
        self.assertTrue(pipeline.validate_scene(sc, ctx, [])[0])


class ExamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = documents.extract((ROOT / "samples" / "Science_notes_plants_and_water.pdf").read_bytes(), "notes.pdf")

    def test_sections_found(self):
        titles = [s["title"] for s in self.doc["sections"]]
        self.assertIn("Photosynthesis", titles)
        self.assertIn("The Water Cycle", titles)

    def test_evidence_must_be_in_the_pdf(self):
        c = self.doc["chunks"][0]
        first = documents.sentences_of(c["text"])[0]
        self.assertEqual(exam.evidence_support(first, c["text"], "q", "True"), "supported")
        self.assertIsNone(exam.evidence_support("The moon is made of green cheese.", c["text"], "What is the moon made of?", "Cheese"))

    def test_offline_questions_are_grounded(self):
        qs = exam.offline_questions(self.doc, ["mcq", "tf"], 8, seed=1)
        self.assertGreaterEqual(len(qs), 5)
        all_text = " ".join(s["text"] for s in self.doc["sentences"])
        for q in qs:
            self.assertIn(q["evidence"], all_text)
            self.assertTrue(0 <= q["answer"] < len(q["options"]))

    def test_not_a_pdf_or_empty_pdf_refused(self):
        with self.assertRaises(documents.DocumentError):
            documents.extract(b"hello", "x.pdf")


class Safety(unittest.TestCase):
    def test_delete_rejects_path_tricks(self):
        for bad in ("../etc", "..", "a/b", "", "x" * 100):
            with self.assertRaises(ValueError):
                pipeline.delete_lesson(bad)

    def test_mp4_verify_rejects_broken_file(self):
        f = ROOT / "data" / "broken_test.mp4"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"not a video" * 2000)
        with self.assertRaises(RuntimeError):
            exporter.verify(f, 30)
        f.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
