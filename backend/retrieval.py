"""Offline retrieval with a relevance check and bounded retries.

Finds the knowledge-base topic (and its facts) that matches what the learner asked, even when the
words differ ("how plants make food" -> photosynthesis).

  * BM25 keyword search over titles, keywords, facts and lesson sentences: always available
  * optional meaning-based (semantic) search with a local Ollama embedding model
    (`ollama pull nomic-embed-text`); used automatically when installed
  * relevance = how much of the query the topic covers; below the threshold the query is
    reformulated (key terms, then corrected terms + subject words) and retried, max 3 attempts
  * if nothing is relevant enough, it says so (topic=None) instead of returning an unrelated topic
"""
import hashlib
import json
import logging
import math
import re
from functools import lru_cache

import requests

from . import config, knowledge

log = logging.getLogger("retrieval")
THRESHOLD = 0.45            # minimum relevance to use a topic's facts
EMBED_MODEL = "nomic-embed-text"
STOP = set("""a an the is are was were be been of to in on for and or how what why when where which who does do did
explain tell me about show teach learn lesson please work works make makes made use can with from by at as it its
this that these those your my our their simple basic intro introduction understand mean meaning""".split())


def tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9]+", str(text).lower()):
        if w in STOP or len(w) < 2:
            continue
        for suf in ("ing", "ed", "es", "s"):           # tiny stemmer: plants -> plant, pumping -> pump
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


@lru_cache(maxsize=1)
def _index():
    docs = []          # (topic_id, kind, text)
    for tid, kb in knowledge.all_topics().items():
        docs.append((tid, "title", kb["lesson"]["title"]))
        docs.append((tid, "keywords", kb["keywords"]))
        for f in kb["facts"]:
            docs.append((tid, "fact", f))
        for sc in kb["lesson"]["scenes"]:
            docs.append((tid, "heading", sc["heading"]))
            for b in sc["narration"]:
                docs.append((tid, "sentence", b["text"]))
    toks = [tokens(t) for _, _, t in docs]
    df = {}
    for ts in toks:
        for w in set(ts):
            df[w] = df.get(w, 0) + 1
    n = len(docs)
    idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
    avgdl = sum(len(t) for t in toks) / max(1, n)
    topic_words = {}
    for (tid, _, _), ts in zip(docs, toks):
        topic_words.setdefault(tid, set()).update(ts)
    return docs, toks, idf, avgdl, topic_words, max(idf.values())


def bm25(query, topic=None, k=8):
    docs, toks, idf, avgdl, _, _ = _index()
    q = tokens(query)
    res = []
    for d, ts in zip(docs, toks):
        if topic and d[0] != topic:
            continue
        tf = {}
        for w in ts:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w in q:
            if w in tf:
                f = tf[w]
                s += idf.get(w, 0) * f * 2.4 / (f + 1.4 * (0.25 + 0.75 * len(ts) / avgdl))
        if s > 0:
            res.append((s, d))
    return sorted(res, key=lambda x: -x[0])[:k]


@lru_cache(maxsize=1)
def _fields():
    """topic -> (core words: title + keywords, body words: facts + sentences, title words)."""
    out = {}
    for tid, kb in knowledge.all_topics().items():
        core = set(tokens(kb["lesson"]["title"] + " " + kb["keywords"]))
        title = set(tokens(kb["lesson"]["title"]))
        body = set()
        for f in kb["facts"]:
            body.update(tokens(f))
        for sc in kb["lesson"]["scenes"]:
            body.update(tokens(sc["heading"] + " " + " ".join(b["text"] for b in sc["narration"])))
        out[tid] = (core, body - core, title)
    return out


BODY_WEIGHT = 0.5           # a word only mentioned in passing counts for little ("car" in a Newton example)
NO_ANCHOR_CAP = 0.30        # no word in the title/keywords: never a match on its own


def coverage(query, topic):
    """How well this topic is *about* the query: 0..1.

    IDF-weighted share of the query's words found in the topic, where title/keyword hits count fully
    and body-only hits count 0.5; at least one title/keyword hit is required; the share of the topic's
    own title that the query mentions breaks ties ("python works" -> Python basics, not Python loops)."""
    _, _, idf, _, _, max_idf = _index()
    q = set(tokens(query))
    if not q:
        return 0.0
    core, body, title = _fields().get(topic, (set(), set(), set()))
    total = sum(idf.get(w, max_idf) for w in q)
    have = sum(idf.get(w, max_idf) * (1.0 if w in core else BODY_WEIGHT if w in body else 0) for w in q)
    score = have / total
    tc = len(q & title) / len(title) if title else 0
    score *= 0.8 + 0.2 * tc
    if not q & core:
        score = min(score, NO_ANCHOR_CAP)
    return score


# ---------------------------------------------------------------- optional semantic search

_emb_state = {"checked": 0.0, "ok": False}


def _embed_available():
    """Is the embedding model installed in Ollama? Re-checked every 60 s (Ollama may start later)."""
    import time
    if time.time() - _emb_state["checked"] > 60:
        _emb_state["checked"] = time.time()
        try:
            r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=2)
            names = [m["name"].split(":")[0] for m in r.json().get("models", [])]
            _emb_state["ok"] = EMBED_MODEL in names
        except Exception:
            _emb_state["ok"] = False
    return _emb_state["ok"]


def _embed(texts):
    # keep_alive -1: keep the search model loaded (otherwise Ollama unloads it after 5 idle minutes and the
    # next new topic waits for it to load again before the AI can even start)
    r = requests.post(f"{config.OLLAMA_URL}/api/embed",
                      json={"model": EMBED_MODEL, "input": texts, "keep_alive": -1}, timeout=60)
    r.raise_for_status()
    return r.json()["embeddings"]


_topic_vecs = {}


def _topic_vectors():
    if _topic_vecs:
        return _topic_vecs
    cache = config.DATA / "embeddings.json"
    store = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    want = {}
    for tid, kb in knowledge.all_topics().items():
        text = "search_document: " + kb["lesson"]["title"] + ". " + " ".join(kb["facts"]) + " " + kb["keywords"]
        want[tid] = (hashlib.sha1(text.encode()).hexdigest(), text)
    missing = [tid for tid, (h, _) in want.items() if store.get(tid, {}).get("h") != h]
    if missing:
        vecs = _embed([want[t][1] for t in missing])
        for t, v in zip(missing, vecs):
            store[t] = {"h": want[t][0], "v": v}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(store), encoding="utf-8")
    _topic_vecs.update({t: store[t]["v"] for t in want})
    return _topic_vecs


def _cos(a, b):
    na = math.sqrt(sum(x * x for x in a)) or 1
    nb = math.sqrt(sum(x * x for x in b)) or 1
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def semantic_scores(query, qv=None):
    """topic -> 0..1 meaning-based relevance, or {} when no embedding model is installed.
    qv: the query's vector if it was already computed (all tries of one topic are embedded in one call)."""
    if not _embed_available():
        return {}
    try:
        if qv is None:
            qv = _embed(["search_query: " + query])[0]
        return {t: max(0.0, min(1.0, (_cos(qv, v) - 0.50) / 0.28)) for t, v in _topic_vectors().items()}
    except Exception as e:
        log.warning("semantic search unavailable: %s", e)
        _emb_state["ok"] = False
        return {}


# ---------------------------------------------------------------- retrieval with bounded retries

def _best(query, qv=None):
    sem = semantic_scores(query, qv)
    best, score, how = None, 0.0, "keywords"
    for tid in knowledge.all_topics():
        c = coverage(query, tid)
        s = max(c, sem.get(tid, 0.0))
        if s > score:
            best, score, how = tid, s, ("meaning" if sem.get(tid, 0) > c else "keywords")
    return best, round(score, 2), how


def retrieve(topic, key_terms=(), fixed_terms=(), domain_words=()):
    """Returns {"topic", "score", "facts", "attempts", "method"}; topic is None if nothing is relevant."""
    queries = [topic]
    if key_terms:
        queries.append(" ".join(key_terms))
    if fixed_terms or domain_words:
        queries.append(" ".join(dict.fromkeys(list(fixed_terms) + list(domain_words))))   # no repeated words
    seen, unique = [], []
    for q in queries:                       # reformulations must really differ from earlier tries
        ts = frozenset(tokens(q or ""))
        if ts and ts not in seen:
            seen.append(ts)
            unique.append(q)
    attempts, chosen = [], None
    vecs = {}
    if unique and _embed_available():
        try:                                   # ONE embedding call for all (up to 3) tries of this topic
            vecs = dict(zip(unique[:3], _embed(["search_query: " + q for q in unique[:3]])))
        except Exception as e:
            log.warning("semantic search unavailable: %s", e)
            _emb_state["ok"] = False
    for q in unique[:3]:                                                             # bounded: max 3 tries
        tid, score, how = _best(q, vecs.get(q))
        attempts.append({"query": q, "topic": tid, "score": score, "how": how})
        if tid and score >= THRESHOLD:
            chosen = attempts[-1]
            break
    method = "keywords + meaning" if _embed_available() else "keywords (BM25)"
    if not chosen:
        best = max(attempts, key=lambda a: a["score"], default=None)
        related = best["topic"] if best and best["topic"] and best["score"] >= 0.25 else None
        return {"topic": None, "score": best["score"] if best else 0, "facts": [], "related": related,
                "attempts": attempts, "method": method}
    kb = knowledge.get(chosen["topic"])
    ranked = [d[2] for _, d in bm25(chosen["query"], chosen["topic"], k=20) if d[1] == "fact"]
    facts = list(dict.fromkeys(ranked + kb["facts"]))[:6]          # most relevant facts first
    return {"topic": chosen["topic"], "score": chosen["score"], "facts": facts, "related": None,
            "attempts": attempts, "method": method}
