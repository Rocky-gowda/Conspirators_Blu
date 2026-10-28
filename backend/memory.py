"""Peak memory while a lesson is made: this app (+ the export browser) and the Ollama model server.

Uses psutil when installed; otherwise reports nothing (it never breaks generation).
"""
import threading
import time

try:
    import psutil
except ImportError:          # optional
    psutil = None

_threads = {}


def _rss_tree(proc):
    total = 0
    try:
        total = proc.memory_info().rss
        for c in proc.children(recursive=True):
            try:
                total += c.memory_info().rss
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    return total


def _ollama_rss():
    total = 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower().startswith("ollama"):
                total += p.memory_info().rss
        except psutil.Error:
            pass
    return total


def start(job):
    if psutil is None:
        return
    me = psutil.Process()
    stop = threading.Event()
    peak = {"app": 0, "ollama": 0, "total": 0}

    def loop():
        while not stop.is_set():
            a, o = _rss_tree(me), _ollama_rss()
            peak["app"], peak["ollama"], peak["total"] = max(peak["app"], a), max(peak["ollama"], o), max(peak["total"], a + o)
            job.memory = {"app_mb": round(peak["app"] / 2**20), "ollama_mb": round(peak["ollama"] / 2**20),
                          "peak_mb": round(peak["total"] / 2**20),
                          "system_mb": round(psutil.virtual_memory().total / 2**20)}
            stop.wait(0.5)
    t = threading.Thread(target=loop, daemon=True)
    _threads[job.id] = stop
    t.start()


def stop(job):
    ev = _threads.pop(job.id, None)
    if ev:
        ev.set()


def snapshot(job):
    return dict(job.memory)
