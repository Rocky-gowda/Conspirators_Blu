"""Load every model ONCE when the server starts, so the first lesson is as fast as the tenth.

Without this, the first request pays for loading the LLM, IndicTrans2 and Kokoro from disk
(often 20-60 s on a laptop). Runs in a background thread; status is shown at /api/warmup.
"""
import logging
import threading
import time

import requests

from . import config

log = logging.getLogger("warmup")
STATUS = {}


def _step(name, fn):
    t0 = time.perf_counter()
    STATUS[name] = "loading"
    try:
        fn()
        STATUS[name] = f"ready ({time.perf_counter() - t0:.1f}s)"
    except Exception as e:  # a missing model must never stop the server
        STATUS[name] = f"not available: {type(e).__name__}: {str(e)[:120]}"
    log.info("warmup %s: %s", name, STATUS[name])


def _llm():
    # loads the model into RAM and keeps it there; also caches the long system prompt
    from .planner import SYSTEM, SYSTEM_COMPACT, pick_model
    model = pick_model()          # never a model that is not installed
    system = SYSTEM_COMPACT if config.COMPACT else SYSTEM      # the instructions every new topic starts with
    requests.post(f"{config.OLLAMA_URL}/api/chat", json={
        "model": model, "stream": False, "keep_alive": -1,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": "Reply OK."}],
        "options": {"num_predict": 2, "num_ctx": 4096}}, timeout=300).raise_for_status()


def _voice():
    from . import tts
    for lang in ("en", "hi"):
        if tts.engine_for(lang) == "kokoro":
            tts.say("Ready.", lang)


def _translate():
    from . import translate
    if any(v["indictrans"] for v in config.LANGS.values()):
        translate.translate_batch(["Hello."], "hi")


def _understanding():
    from . import topic_nlp
    topic_nlp.analyze("how do plants make food")     # loads the spelling dictionary and search index


def _search():
    from . import retrieval
    retrieval._emb_state["checked"] = 0.0
    if not retrieval._embed_available():
        raise RuntimeError("keyword search only; run 'ollama pull nomic-embed-text' to add meaning-based search")
    retrieval._topic_vectors()                       # embeds the offline notes once (cached on disk)


def run():
    for name, fn in (("understanding", _understanding), ("llm", _llm), ("meaning search", _search),
                     ("voice", _voice), ("translate", _translate)):
        _step(name, fn)


def start():
    threading.Thread(target=run, daemon=True).start()
