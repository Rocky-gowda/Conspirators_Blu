"""A fake Ollama for testing the streaming pipeline without a real model.

    python -m uvicorn tests.fake_ollama:app --port 11434

It answers /api/chat by streaming a knowledge-base lesson matching the topic in the prompt, a few
characters per chunk with a delay (like a slow CPU), in the same field order as the schema.
Env FAKE_TPS = chunks per second (default 40), FAKE_MODE = ok | short | broken | stall
"""
import json
import os
import re
import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import knowledge, topic_nlp  # noqa: E402

app = FastAPI()

KOHLI = {"title": "Virat Kohli", "scenes": [
    {"type": "title_card", "heading": "Who is Virat Kohli?", "subtitle": "An Indian cricketer",
     "narration": [{"text": "Virat Kohli is one of India's best known cricket batsmen."}]},
    {"type": "timeline", "heading": "Step 1: His cricket journey", "events": [
        {"label": "1988", "text": "Born in Delhi"}, {"label": "2008", "text": "Won the Under-19 World Cup as captain"},
        {"label": "2011", "text": "Part of India's World Cup winning team"}],
     "narration": [{"text": "Virat Kohli was born in Delhi in nineteen eighty-eight.", "focus": 0},
                   {"text": "In two thousand eight he captained India to the Under-19 World Cup.", "focus": 1},
                   {"text": "In two thousand eleven he was part of the team that won the World Cup.", "focus": 2}]},
    {"type": "diagram", "layout": "stack", "heading": "Step 2: What makes him special",
     "items": ["Consistent batting", "Fitness", "Leadership"], "icons": ["🏏", "💪", "🧢"],
     "narration": [{"text": "He is known for scoring runs consistently.", "focus": 0},
                   {"text": "He made fitness a priority for Indian cricketers.", "focus": 1},
                   {"text": "He also captained the Indian team.", "focus": 2}]},
    {"type": "quiz", "heading": "Quick check", "question": "Which sport does Virat Kohli play?",
     "options": ["Cricket", "Football", "Hockey"], "answer": 0,
     "narration": [{"text": "Quick check. Which sport does he play?"}, {"text": "Cricket.", "focus": 0}]}]}
# written only when the prompt carries feedback: proves the retry-with-reasons path (real dates)
FRENCH = {"title": "The French Revolution", "scenes": [
    {"type": "title_card", "heading": "The French Revolution", "subtitle": "France, 1789 to 1799",
     "narration": [{"text": "The French Revolution changed how France was ruled."}]},
    {"type": "timeline", "heading": "Step 1: Key events", "events": [
        {"label": "1789", "text": "The Bastille prison is stormed"}, {"label": "1792", "text": "France becomes a republic"},
        {"label": "1799", "text": "Napoleon takes power"}],
     "narration": [{"text": "In seventeen eighty-nine, crowds stormed the Bastille prison in Paris.", "focus": 0},
                   {"text": "In seventeen ninety-two, the king was removed and France became a republic.", "focus": 1},
                   {"text": "In seventeen ninety-nine, Napoleon Bonaparte took power.", "focus": 2}]},
    {"type": "diagram", "layout": "flow", "heading": "Step 2: Why the revolution began",
     "items": ["Unfair taxes", "Food shortages", "Ideas of equality", "Revolt against the king"],
     "narration": [{"text": "Ordinary people paid heavy taxes, while nobles paid little.", "focus": 0},
                   {"text": "Bread was scarce and expensive.", "focus": 1},
                   {"text": "New ideas said all citizens should have equal rights.", "focus": 2},
                   {"text": "Together these led people to rise against the king.", "focus": 3}]},
    {"type": "quiz", "heading": "Quick check", "question": "In which year was the Bastille stormed?",
     "options": ["1789", "1799", "1857"], "answer": 0,
     "narration": [{"text": "Quick check. When was the Bastille stormed?"}, {"text": "In seventeen eighty-nine.", "focus": 0}]}],
    "prerequisites": ["What is a monarchy?"], "next_topics": ["Napoleon Bonaparte"]}
LAST = {}


def to_compact(sc):
    """A full scene -> the compact format a real model would write when asked for it."""
    t, says = sc["type"], [b["text"] for b in sc["narration"]]
    c = {"h": sc.get("heading", ""), "s": says}
    if t == "quiz":
        c.update(q=sc["question"], o=sc["options"], a=sc["answer"])
    elif t == "diagram":
        c["l"] = sc["items"]
    elif t == "timeline":
        c["l"] = [f"{e['label']}: {e['text']}" for e in sc["events"]]
    elif t == "illustration":
        c["l"] = [f"{p['role']}: {p['label']}" for p in sc["parts"]]
    elif t == "shape":
        c["l"] = [f"{p['part']}: {p['label']}" for p in sc["parts"]]
    elif t == "worked_example":
        c.update(p=sc["problem"], l=sc["steps"], ans=sc["answer"])
    elif t == "code_walkthrough":
        c.update(c=sc["code"], out=sc.get("output") or [])
    elif t == "chart":
        c.update(l=[f"{a}: {v:g}" for a, v in zip(sc["labels"], sc["values"])], u=sc.get("unit") or "")
    elif t == "table":
        c["l"] = [" | ".join(sc["columns"])] + [" | ".join(r) for r in sc["rows"]]
    return c


@app.get("/api/tags")
def tags():
    return {"models": [{"name": "phi4-mini:latest"}, {"name": "qwen3:1.7b"}]}


@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    LAST["body"] = body
    prompt = body["messages"][-1]["content"]
    if prompt.startswith("Passage (page"):              # Exam Mode question request
        passage = re.search(r'"""(.*?)"""', prompt, re.S).group(1)
        sents = re.split(r"(?<=[.!?])\s+", passage.strip())
        qs = [{"type": "tf", "question": "True or false: " + sents[0], "options": ["True", "False"], "answer": 0,
               "explanation": "The passage says so.", "evidence": sents[0]},
              {"type": "mcq", "question": "What is the moon made of?", "options": ["Cheese", "Rock", "Gas", "Ice"],
               "answer": 0, "explanation": "Made up.", "evidence": "The moon is made of green cheese."}]
        text = json.dumps({"questions": qs})
        time.sleep(0.2)
        return StreamingResponse(iter([json.dumps({"message": {"content": text}, "done": True}) + "\n"]),
                                 media_type="application/x-ndjson")
    topic = re.search(r"Topic: (.*)", prompt).group(1)
    level = re.search(r"Level: (\w+)", prompt).group(1)
    secs = int(re.search(r"about (\d+) seconds", prompt).group(1))
    info = topic_nlp.analyze(topic)
    if "Write ONLY ONE new teaching scene" in prompt:       # smart-validation re-ask: one scene
        sc = KOHLI["scenes"][2] if "Kohli" in topic else \
            knowledge.assemble(info["kb"] or "python_loop", level, 90).model_dump()["scenes"][1]
        text = json.dumps(sc)
        return StreamingResponse(iter([json.dumps({"message": {"content": text}, "done": True}) + "\n"]),
                                 media_type="application/x-ndjson")
    if "Kohli" in topic:
        L = dict(KOHLI, prerequisites=["Cricket basics"], next_topics=["History of Indian cricket"])
    elif "French Revolution" in topic and "Your previous answer was not usable" in prompt:
        L = FRENCH
    else:
        L = knowledge.assemble(info["kb"] or "python_loop", level, secs).model_dump()
    scenes = L["scenes"]
    if os.environ.get("FAKE_MODE") == "person_short":
        scenes = scenes[:2]
    mode = os.environ.get("FAKE_MODE", "ok")
    if mode == "short":
        scenes = scenes[:2]
    if mode == "broken":   # typical small-model mistakes
        scenes[1]["narration"][0]["focus"] = 42
        scenes[-1]["options"] = [f"{'ABCD'[i]}) {o}" for i, o in enumerate(scenes[-1]["options"])]
        scenes.insert(1, {"type": "video", "heading": "nope", "narration": [{"text": "bad scene"}]})
    doc = {"title": L["title"], "scenes": scenes, "prerequisites": L["prerequisites"][:2],
           "next_topics": L["next_topics"][:3]}
    if body["messages"][0]["content"].startswith("You are an expert teacher") and \
            "Return ONLY compact JSON" in body["messages"][0]["content"]:
        doc = {"title": L["title"], "scenes": [to_compact(x) for x in scenes if x["type"] != "title_card"]}
        if mode == "lazy":                    # a small model that writes only headings and sentences
            doc["scenes"] = [{"h": x["h"], "s": x["s"]} for x in doc["scenes"]]
    text = json.dumps(doc, ensure_ascii=False)
    tps = float(os.environ.get("FAKE_TPS", "40"))

    def gen():
        if body.get("stream") is False:
            yield json.dumps({"message": {"content": text}, "done": True}) + "\n"
            return
        for i in range(0, len(text), 4):
            time.sleep(1 / tps)
            if mode == "stall" and i > len(text) // 3:
                time.sleep(3600)
            yield json.dumps({"message": {"content": text[i:i + 4]}, "done": False}) + "\n"
        yield json.dumps({"message": {"content": ""}, "done": True}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")
