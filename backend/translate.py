"""Stage 4a: translate an English lesson into an Indian language with IndicTrans2 (local).

Code, numbers-in-code and terms wrapped in `backticks` stay in English.
"""
import copy
import logging
import re
import threading

from . import config
from .schema import Lesson

log = logging.getLogger("translate")
_lock = threading.Lock()
_model = None

# Words students say in English in Indian classrooms. Extend freely.
KEEP_ENGLISH = ["Python", "Java", "JavaScript", "for loop", "while loop", "loop", "range", "print",
                "function", "variable", "array", "CPU", "RAM", "DNA", "HTML", "API", "algorithm"]


class MiniProcessor:
    """Small pure-Python stand-in for IndicTransToolkit's IndicProcessor (which needs a C++ compiler
    on Windows). Pre: add the language tags IndicTrans2 expects. Post: convert any Devanagari output
    to the target script (no-op when the model already wrote the target script)."""
    XLIT = {"kan_Knda": "kn", "ben_Beng": "bn", "tam_Taml": "ta", "tel_Telu": "te", "guj_Gujr": "gu",
            "pan_Guru": "pa", "ory_Orya": "or", "mal_Mlym": "ml"}

    def __init__(self):
        from indicnlp.transliterate.unicode_transliterate import UnicodeIndicTransliterator
        self.x = UnicodeIndicTransliterator

    def preprocess_batch(self, sents, src_lang, tgt_lang):
        return [f"{src_lang} {tgt_lang} " + re.sub(r"\s+", " ", s).strip() for s in sents]

    def postprocess_batch(self, sents, lang):
        out = []
        for s in sents:
            s = re.sub(r"\s+", " ", s).strip()
            if lang in self.XLIT:
                s = self.x.transliterate(s, "hi", self.XLIT[lang])
                if lang != "ben_Beng":
                    s = s.replace("।", ".")
            out.append(s)
        return out


def _load():
    global _model
    if _model is None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(config.INDICTRANS_MODEL, trust_remote_code=True)
        mdl = AutoModelForSeq2SeqLM.from_pretrained(config.INDICTRANS_MODEL, trust_remote_code=True)
        mdl.eval()
        import os
        torch.set_num_threads(max(1, os.cpu_count() or 4))
        _model = (tok, mdl, MiniProcessor())
    return _model


def _protect(text: str):
    """Swap protected terms for placeholders IndicTrans2 leaves alone."""
    terms = []

    def sub(m):
        terms.append(m.group(1) if m.group(1) else m.group(0))
        return f"<ID{len(terms)}>"
    text = re.sub(r"`([^`]+)`", sub, text)
    for w in sorted(KEEP_ENGLISH, key=len, reverse=True):
        text = re.sub(rf"(?<![\w<])({re.escape(w)})(?![\w>])", sub, text)
    return text, terms


def _restore(text: str, terms):
    for i, t in enumerate(terms, 1):
        text = re.sub(rf"<\s*ID\s*{i}\s*>", t, text)
    return text


def translate_batch(sentences, lang: str):
    if not sentences:
        return []
    tgt = config.LANGS[lang]["indictrans"]
    import torch
    tok, mdl, ip = _load()
    prot = [_protect(s) for s in sentences]
    with _lock, torch.no_grad():
        batch = ip.preprocess_batch([p[0] for p in prot], src_lang="eng_Latn", tgt_lang=tgt)
        inputs = tok(batch, truncation=True, padding="longest", return_tensors="pt")
        out = mdl.generate(**inputs, use_cache=True, min_length=0, max_length=256, num_beams=config.TRANSLATE_BEAMS)
        dec = tok.batch_decode(out, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        dec = ip.postprocess_batch(dec, lang=tgt)
    res = []
    for (src, terms), t, orig in zip(prot, dec, sentences):
        r = _restore(t, terms)
        if "<ID" in r or "< ID" in r:  # placeholder got mangled: retranslate unprotected
            log.warning("placeholder lost, using unprotected translation for: %s", orig)
            r = translate_plain(orig, lang)
        res.append(r)
    return res


def translate_plain(sentence, lang):
    import torch
    tgt = config.LANGS[lang]["indictrans"]
    tok, mdl, ip = _load()
    with _lock, torch.no_grad():
        b = ip.preprocess_batch([sentence.replace("`", "")], src_lang="eng_Latn", tgt_lang=tgt)
        x = tok(b, return_tensors="pt", padding="longest")
        o = mdl.generate(**x, max_length=256, num_beams=config.TRANSLATE_BEAMS)
        return ip.postprocess_batch(tok.batch_decode(o, skip_special_tokens=True), lang=tgt)[0]


def _looks_like_code(s: str) -> bool:
    # formulas and code stay in English; plain text with numbers ("2 times") is translated
    return bool(re.search(r"[=(){}\[\]<>+*/×÷_²³√⁻→]", s))


def _translatable(s) -> bool:
    return bool(s) and isinstance(s, str) and not _looks_like_code(s) and bool(re.search(r"[A-Za-z]{2}", s))


_memo = {}  # (lang, text) -> translation; makes revoice / edit / prebake of shared sentences instant


def translate_texts(texts, lang):
    """Translate a list of strings, keeping code/formulas and remembering earlier results."""
    if lang == "en":
        return list(texts)
    todo = [t for t in dict.fromkeys(texts) if _translatable(t) and (lang, t) not in _memo]
    if todo:
        for src, dst in zip(todo, translate_batch(todo, lang)):
            _memo[(lang, src)] = dst.strip() or src
    return [_memo.get((lang, t), t) for t in texts]


def _slots(sc):
    """(object, field, index) for every text the learner sees or hears in one scene."""
    out = [(sc, "heading", None)]
    if sc.type == "title_card" and sc.subtitle:
        out.append((sc, "subtitle", None))
    if sc.type == "diagram":
        out += [(sc, "items", i) for i in range(len(sc.items))]
        out += [(sc, "edge_labels", i) for i in range(len(sc.edge_labels or []))]
    if sc.type == "timeline":
        for e in sc.events:
            out.append((e, "text", None))
            if not re.fullmatch(r"[\d\s,.\-–]+", e.label):   # years stay as they are
                out.append((e, "label", None))
    if sc.type == "chart":
        out += [(sc, "labels", i) for i in range(len(sc.labels))]
        if sc.chart_title:
            out.append((sc, "chart_title", None))
    if sc.type == "worked_example":
        out += [(sc, "problem", None), (sc, "answer", None)]
        out += [(sc, "steps", i) for i in range(len(sc.steps))]
    if sc.type == "table":
        out += [(sc, "columns", i) for i in range(len(sc.columns))]
        out += [(sc, "rows", (ri, ci)) for ri, r in enumerate(sc.rows) for ci in range(len(r)) if r[ci].strip()]
    if sc.type == "shape":
        out += [(prt, "label", None) for prt in sc.parts]
    if sc.type == "illustration":
        for prt in sc.parts:
            out.append((prt, "label", None))
            if prt.via:
                out.append((prt, "via", None))
    if sc.type == "quiz":
        out.append((sc, "question", None))
        out += [(sc, "options", i) for i in range(len(sc.options))]
    out += [(b, "text", None) for b in sc.narration]
    return out


def _get(o, f, i):
    if i is None:
        return getattr(o, f)
    if isinstance(i, tuple):                       # a table cell: rows[row][column]
        return getattr(o, f)[i[0]][i[1]]
    return getattr(o, f)[i]


def _apply(slots, lang):
    vals = [_get(o, f, i) for o, f, i in slots]
    done = translate_texts(vals, lang)
    for (o, f, i), v in zip(slots, done):
        if i is None:
            setattr(o, f, v)
        elif isinstance(i, tuple):
            getattr(o, f)[i[0]][i[1]] = v
        else:
            getattr(o, f)[i] = v


def translate_scene(scene, lang):
    if lang == "en":
        return scene
    sc = copy.deepcopy(scene)
    _apply(_slots(sc), lang)
    return sc


def translate_lesson(lesson: Lesson, lang: str) -> Lesson:
    if lang == "en":
        return lesson
    out = copy.deepcopy(lesson)
    slots = [(out, "title", None)]
    for sc in out.scenes:
        slots += _slots(sc)
    _apply(slots, lang)          # one batch: fastest for whole lessons
    out.language = lang
    return out
