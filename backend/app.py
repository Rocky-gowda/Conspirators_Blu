"""FastAPI server. Run:  python -m uvicorn backend.app:app --port 8000"""
import logging
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import json
import threading

from fastapi import Request

from . import config, documents, exam, knowledge, pipeline, planner, topic_nlp, warmup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
app = FastAPI(title="Blu Visual Teacher")


@app.on_event("startup")
def _warm():
    warmup.start()  # load all models in the background so the first lesson is fast


@app.get("/api/warmup")
def warmup_status():
    return warmup.STATUS


class GenerateReq(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    language: str = "en"
    seconds: int = Field(default=60, ge=30, le=90)
    gender: Literal["female", "male"] = "female"
    speed: float = Field(default=1.0, ge=0.7, le=1.3)
    force: bool = False
    model: Optional[str] = Field(default=None, max_length=80)   # optional override; normally auto-selected
    confirm: bool = False      # learner chose "continue as typed" for a broad or unclear topic


class RevoiceReq(BaseModel):
    language: str
    gender: Literal["female", "male"] = "female"
    speed: float = Field(default=1.0, ge=0.7, le=1.3)


class EditReq(BaseModel):
    scene: dict


def _check_lang(code):
    if code not in config.LANGS:
        raise HTTPException(400, f"unsupported language {code}")


@app.get("/api/languages")
def languages():
    return [{"code": k, "name": v["name"], "font": v["font"]} for k, v in config.LANGS.items()]


@app.get("/api/models")
def models():
    """Planner models installed in the local Ollama (for the model picker)."""
    return {"default": config.OLLAMA_MODEL, "installed": planner.installed_models()}


@app.get("/api/analyze")
def analyze(topic: str):
    """Live preview of how the topic is understood (typo fixes, subject, knowledge match)."""
    a = topic_nlp.analyze(topic)
    kb = knowledge.get(a["kb"]) if a["kb"] else None
    a["kb_title"] = kb["lesson"]["title"] if kb else None
    return a


@app.get("/api/history")
def history():
    return pipeline.history()


@app.delete("/api/history")
def clear_history():
    return {"deleted": pipeline.clear_history()}


@app.delete("/api/lessons/{lesson_id}")
def delete_lesson(lesson_id: str):
    try:
        if not pipeline.delete_lesson(lesson_id):
            raise HTTPException(404, "lesson not found")
    except ValueError:
        raise HTTPException(400, "bad lesson id")
    return {"deleted": lesson_id}


@app.get("/api/lessons/{lesson_id}/meta")
def lesson_meta(lesson_id: str):
    f = pipeline.lesson_dir(lesson_id) / "meta.json"
    if not f.exists():
        raise HTTPException(404, "lesson not finished yet")
    return json.loads(f.read_text(encoding="utf-8"))


@app.post("/api/generate")
def generate(req: GenerateReq):
    _check_lang(req.language)
    a = topic_nlp.analyze(req.topic)
    if a["status"] == "invalid":
        raise HTTPException(400, {"message": a["message"], "analysis": a})
    if a["status"] in ("broad", "unclear") and not req.confirm:
        # ask the learner instead of guessing: the page shows the suggestions
        raise HTTPException(409, {"message": a["message"], "analysis": a})
    return pipeline.start("generate", req.model_dump()).to_dict()


@app.post("/api/lessons/{lesson_id}/revoice")
def revoice(lesson_id: str, req: RevoiceReq):
    _check_lang(req.language)
    if not (pipeline.lesson_dir(lesson_id) / "lesson.en.json").exists():
        raise HTTPException(404, "lesson not found")
    return pipeline.start("revoice", {"lesson_id": lesson_id, **req.model_dump()}).to_dict()


@app.post("/api/lessons/{lesson_id}/scenes/{index}")
def edit_scene(lesson_id: str, index: int, req: EditReq):
    if not (pipeline.lesson_dir(lesson_id) / "timeline.json").exists():
        raise HTTPException(404, "lesson not found")
    return pipeline.start("edit", {"lesson_id": lesson_id, "scene_index": index, "scene": req.scene}).to_dict()


# ---------------------------------------------------------------- Exam Mode

class ExamReq(BaseModel):
    doc_id: str
    count: int = Field(default=10, ge=3, le=30)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    types: list = Field(default_factory=lambda: ["mcq", "tf"])
    language: str = "en"
    minutes: int = Field(default=0, ge=0, le=180)
    use_ai: bool = True


class SubmitReq(BaseModel):
    answers: dict
    seconds_taken: Optional[int] = None


@app.post("/api/exam/upload")
async def exam_upload(request: Request, name: str = "notes.pdf"):
    """The PDF is sent as the raw request body (no extra upload library needed)."""
    data = await request.body()
    try:
        return documents.summary(documents.extract(data, name))
    except documents.DocumentError as e:
        raise HTTPException(400, str(e))


@app.post("/api/exam/create")
def exam_create(req: ExamReq):
    _check_lang(req.language)
    try:
        documents.load(req.doc_id)
    except documents.DocumentError as e:
        raise HTTPException(400, str(e))
    job = pipeline.Job("exam", req.model_dump())

    def run():
        job.status = "running"
        job.stage = "questions"
        try:
            with pipeline._run_lock:
                e = exam.create(job, req.doc_id, req.count, req.difficulty, req.types, req.language, req.minutes, req.use_ai)
            job.notes = e["notes"]
            job.lesson_id = e["id"]          # the exam id
            job.timings["questions"] = e["seconds_to_make"]
            job.status = "done"
        except Exception as ex:
            job.error, job.status = str(ex), "error"
    threading.Thread(target=run, daemon=True).start()
    return job.to_dict()


@app.get("/api/exam/{exam_id}")
def exam_get(exam_id: str):
    try:
        return exam.public(exam_id)
    except documents.DocumentError as e:
        raise HTTPException(404, str(e))


@app.post("/api/exam/{exam_id}/submit")
def exam_submit(exam_id: str, req: SubmitReq):
    try:
        return exam.grade(exam_id, req.answers, req.seconds_taken)
    except documents.DocumentError as e:
        raise HTTPException(404, str(e))


@app.get("/api/exams")
def exams():
    return exam.list_exams()


@app.delete("/api/exam/{exam_id}")
def exam_delete(exam_id: str):
    try:
        exam.delete(exam_id)
    except documents.DocumentError as e:
        raise HTTPException(404, str(e))
    return {"deleted": exam_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    j = pipeline.JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j.to_dict()


config.LESSONS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/lessons", StaticFiles(directory=config.LESSONS_DIR), name="lessons")
app.mount("/", StaticFiles(directory=config.FRONTEND, html=True), name="frontend")
