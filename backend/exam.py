"""Exam Mode, step 2: questions grounded in the uploaded PDF, then marking and weak areas.

  * AI questions: the local model writes questions from ONE passage at a time and must copy an
    evidence sentence from that passage. We keep a question only if the evidence really is in the
    PDF ("supported"); if only its words are, it is labelled "inferred"; otherwise it is dropped.
  * Offline questions (no AI needed, instant): fill-in-the-blank and true/false built directly from
    sentences of the PDF, with the sentence itself as evidence.
  * Answers never leave the server before the student submits.
"""
import difflib
import json
import logging
import random
import re
import time
import uuid
from datetime import datetime

import requests

from . import config, documents, planner, translate

log = logging.getLogger("exam")
EXAMS = config.DATA / "exams"

Q_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": 2, "items": {
        "type": "object",
        "properties": {
            "type": {"enum": ["mcq", "tf"]},
            "question": {"type": "string", "maxLength": 200},
            "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string", "maxLength": 90}},
            "answer": {"type": "integer", "minimum": 0, "maximum": 3},
            "explanation": {"type": "string", "maxLength": 240},
            "evidence": {"type": "string", "maxLength": 300}},
        "required": ["type", "question", "options", "answer", "explanation", "evidence"]}}},
    "required": ["questions"]}

DIFF = {"easy": "EASY: recall a fact stated directly in the passage.",
        "medium": "MEDIUM: test understanding of an idea in the passage (why or how), not just a word.",
        "hard": "HARD: apply or connect ideas from the passage; distractors must be plausible."}

SYSTEM = ("You write fair exam questions for students. Use ONLY the passage given. Never use outside knowledge. "
          "For every question copy one sentence from the passage word for word into 'evidence'. "
          "Return JSON only.")


def _norm(s):
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def evidence_support(evidence, chunk_text, question, answer_text):
    """'supported' if the evidence sentence is really in the passage, 'inferred' if only its content is."""
    ev = _norm(evidence)
    sents = [_norm(x) for x in documents.sentences_of(chunk_text)] or [_norm(chunk_text)]
    if ev and (ev in _norm(chunk_text) or max(difflib.SequenceMatcher(None, ev, s).ratio() for s in sents) >= 0.82):
        return "supported"
    words = set(_norm(question + " " + answer_text).split()) - documents.STOP
    have = set(_norm(chunk_text).split())
    if words and len(words & have) / len(words) >= 0.6 and set(_norm(answer_text).split()) <= have | {"true", "false"}:
        return "inferred"
    return None


def _ask_llm(chunk, n, difficulty, types, model):
    want = " or ".join({"mcq": "multiple choice (4 options)", "tf": "true/false"}[t] for t in types)
    prompt = (f"Passage (page {chunk['page']}):\n\"\"\"{chunk['text']}\"\"\"\n\nWrite {n} {want} question(s). "
              f"{DIFF[difficulty]} For true/false use options [\"True\", \"False\"]. 'answer' is the index of the "
              "correct option. The explanation must say why, using the passage.")
    body = {"model": model, "stream": False, "keep_alive": -1, "format": Q_SCHEMA,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            "options": {"temperature": 0.3, "num_ctx": 4096, "num_predict": 600}}
    if model.startswith(("qwen3", "deepseek-r1")):
        body["think"] = False
    r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=(10, config.PLANNER_STALL_S))
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"]).get("questions", [])


def _clean_q(q, chunk, types):
    t = q.get("type")
    if t not in types:
        return None
    opts = [re.sub(r"^\s*(\(?[A-Da-d1-4][\).:]|[A-Da-d]\s*-)\s+", "", str(o)).strip() for o in q.get("options", [])]
    if t == "tf":
        opts = ["True", "False"]
    if len(opts) < 2 or len({o.lower() for o in opts}) != len(opts):
        return None
    try:
        ans = int(q.get("answer"))
    except (TypeError, ValueError):
        return None
    if not 0 <= ans < len(opts) or not str(q.get("question", "")).strip():
        return None
    support = evidence_support(str(q.get("evidence", "")), chunk["text"], q["question"], opts[ans])
    if not support:
        return None
    return {"type": t, "question": q["question"].strip(), "options": opts, "answer": ans,
            "explanation": str(q.get("explanation", "")).strip(), "evidence": str(q.get("evidence", "")).strip(),
            "page": chunk["page"], "section": chunk["section"], "support": support, "source": "ai"}


def offline_questions(doc, types, n, seed=0):
    """Fill-in-the-blank and true/false questions straight from the PDF's sentences (no AI)."""
    rnd = random.Random(seed)
    terms = [t for t in doc["key_terms"] if " " not in t or len(t) < 30]
    out, used = [], set()
    sents = doc["sentences"][:]
    rnd.shuffle(sents)
    for s in sents:
        if len(out) >= n:
            break
        text = s["text"]
        low = text.lower()
        hits = [t for t in terms if re.search(rf"\b{re.escape(t)}\b", low)]
        if not hits or text in used:
            continue
        term = max(hits, key=len)
        # distractors: other key terms of the notes, similar in length and in word count
        others = [t for t in terms if t != term and t not in low and term not in t
                  and abs(len(t) - len(term)) < 10 and (" " in t) == (" " in term)]
        if len(others) < 3:
            others = [t for t in terms if t != term and t not in low and term not in t]
        if len(others) < 3:
            continue
        used.add(text)
        kind = "mcq" if ("mcq" in types and (len(out) % 2 == 0 or "tf" not in types)) else "tf"
        if kind == "mcq":
            blank = re.sub(rf"\b{re.escape(term)}\b", "_____", text, count=1, flags=re.I)
            opts = rnd.sample(others, 3) + [term]
            rnd.shuffle(opts)
            out.append({"type": "mcq", "question": f"Fill in the blank: {blank}", "options": opts,
                        "answer": opts.index(term), "explanation": f"The notes say: “{text}”", "evidence": text,
                        "page": s["page"], "section": s["section"], "support": "supported", "source": "offline"})
        else:
            truth = rnd.random() < 0.5
            stmt = text if truth else re.sub(rf"\b{re.escape(term)}\b", rnd.choice(others), text, count=1, flags=re.I)
            out.append({"type": "tf", "question": f"True or false: {stmt}", "options": ["True", "False"],
                        "answer": 0 if truth else 1,
                        "explanation": ("This is stated in the notes." if truth else f"The notes say “{term}”, not this."),
                        "evidence": text, "page": s["page"], "section": s["section"], "support": "supported",
                        "source": "offline"})
    return out


def _similar(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio() > 0.8


def create(job, doc_id, count=10, difficulty="medium", types=("mcq", "tf"), language="en", minutes=0, use_ai=True):
    doc = documents.load(doc_id)
    types = [t for t in types if t in ("mcq", "tf")] or ["mcq"]
    qs, notes = [], []
    t0 = time.perf_counter()
    if use_ai:
        try:
            model = planner.pick_model()
            chunks = sorted(doc["chunks"], key=lambda c: (c["section"], c["id"]))
            # spread the questions over the sections of the document
            by_sec = {}
            for c in chunks:
                by_sec.setdefault(c["section"], []).append(c)
            order = []
            while any(by_sec.values()):
                for k in list(by_sec):
                    if by_sec[k]:
                        order.append(by_sec[k].pop(0))
            for c in order:
                if len(qs) >= count or time.perf_counter() - t0 > 360:
                    break
                job.detail = f"writing questions from page {c['page']} ({len(qs)}/{count} ready)"
                try:
                    for q in _ask_llm(c, 1 if count <= len(order) else 2, difficulty, types, model):
                        cq = _clean_q(q, c, types)
                        if cq and not any(_similar(cq["question"], x["question"]) for x in qs):
                            qs.append(cq)
                        elif not cq:
                            notes.append(f"dropped a question from page {c['page']}: not supported by the PDF")
                except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
                    notes.append(f"AI question failed on page {c['page']} ({type(e).__name__})")
                job.progress = min(0.95, len(qs) / count)
            notes.insert(0, f"{len(qs)} questions written by {model}")
        except planner.ModelUnavailable as e:
            notes.append(f"{e} Using offline questions built from the PDF instead.")
    if len(qs) < count:
        extra = [q for q in offline_questions(doc, types, count * 2, seed=len(doc["sentences"]))
                 if not any(_similar(q["evidence"], x["evidence"]) for x in qs)]
        add = extra[: count - len(qs)]
        if add:
            notes.append(f"{len(add)} questions made offline from the PDF's own sentences")
        qs += add
    if not qs:
        raise documents.DocumentError("Not enough clear sentences in this PDF to make questions.")
    for i, q in enumerate(qs):
        q["id"] = i
    if language != "en":
        try:
            for q in qs:
                vals = translate.translate_texts([q["question"], q["explanation"]] + q["options"], language)
                q["question"], q["explanation"], q["options"] = vals[0], vals[1], vals[2:]
        except Exception as e:
            notes.append(f"translation unavailable ({type(e).__name__}); questions are in English")
            language = "en"
    exam_id = uuid.uuid4().hex[:10]
    exam = {"id": exam_id, "doc_id": doc_id, "doc_name": doc["name"], "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "settings": {"count": count, "difficulty": difficulty, "types": types, "language": language, "minutes": minutes},
            "sections": doc["sections"], "questions": qs, "notes": notes, "attempts": [],
            "seconds_to_make": round(time.perf_counter() - t0, 1)}
    EXAMS.mkdir(parents=True, exist_ok=True)
    (EXAMS / f"{exam_id}.json").write_text(json.dumps(exam, ensure_ascii=False, indent=1), encoding="utf-8")
    return exam


def _load(exam_id):
    if not re.fullmatch(r"[0-9a-f]{10}", exam_id or ""):
        raise documents.DocumentError("bad exam id")
    f = EXAMS / f"{exam_id}.json"
    if not f.exists():
        raise documents.DocumentError("exam not found")
    return json.loads(f.read_text(encoding="utf-8"))


def public(exam_id):
    """The exam as the student sees it: no answers, explanations or evidence."""
    e = _load(exam_id)
    return {"id": e["id"], "doc_name": e["doc_name"], "settings": e["settings"], "notes": e["notes"],
            "questions": [{"id": q["id"], "type": q["type"], "question": q["question"], "options": q["options"],
                           "page": q["page"], "support": q["support"]} for q in e["questions"]],
            "attempts": [{"percent": a["percent"], "date": a["date"]} for a in e["attempts"]]}


def grade(exam_id, answers: dict, seconds_taken=None):
    e = _load(exam_id)
    secs = {s["id"]: s["title"] for s in e["sections"]}
    rows, by_sec = [], {}
    for q in e["questions"]:
        given = answers.get(str(q["id"]))
        ok = given is not None and int(given) == q["answer"]
        rows.append({"id": q["id"], "question": q["question"], "options": q["options"], "your": given,
                     "answer": q["answer"], "correct": ok, "explanation": q["explanation"], "evidence": q["evidence"],
                     "page": q["page"], "section": secs.get(q["section"], "Notes"), "support": q["support"]})
        st = by_sec.setdefault(secs.get(q["section"], "Notes"), {"correct": 0, "total": 0})
        st["total"] += 1
        st["correct"] += ok
    score = sum(r["correct"] for r in rows)
    percent = round(100 * score / max(1, len(rows)))
    sections = [{"title": k, **v, "percent": round(100 * v["correct"] / v["total"])} for k, v in by_sec.items()]
    weak = [s["title"] for s in sorted(sections, key=lambda s: s["percent"]) if s["percent"] < 60]
    res = {"score": score, "total": len(rows), "percent": percent, "answered": sum(r["your"] is not None for r in rows),
           "sections": sections, "weak": weak, "rows": rows, "seconds_taken": seconds_taken}
    e["attempts"].append({"percent": percent, "score": score, "date": datetime.now().astimezone().isoformat(timespec="seconds")})
    (EXAMS / f"{exam_id}.json").write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    res["attempts"] = [{"percent": a["percent"], "date": a["date"]} for a in e["attempts"]]
    return res


def list_exams():
    out = []
    for f in sorted(EXAMS.glob("*.json")) if EXAMS.exists() else []:
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"id": e["id"], "doc_name": e["doc_name"], "created": e["created"], "count": len(e["questions"]),
                    "best": max([a["percent"] for a in e["attempts"]], default=None), "attempts": len(e["attempts"])})
    return sorted(out, key=lambda x: x["created"], reverse=True)


def delete(exam_id):
    _load(exam_id)
    (EXAMS / f"{exam_id}.json").unlink()
