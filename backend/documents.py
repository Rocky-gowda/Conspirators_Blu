"""Exam Mode, step 1: read a PDF locally and split it into sections, chunks, sentences and key terms.

Text PDFs only (scanned images have no text layer; we say so instead of guessing).
"""
import hashlib
import io
import json
import re
from collections import Counter

from . import config

DOCS = config.DATA / "docs"
STOP = set("""a an the and or but if then than of to in on at by for from with without into onto over under is are was
were be been being it its this that these those there here which who whom whose what when where why how not no can
could should would may might will shall do does did done has have had having as so such also very more most less
least each every some any all both either neither one two three first second their they them he she his her we our
you your i me my about between within during before after above below up down out off again further once only own
same too just because while until per via etc used use using called known make makes made many much other others
amount amounts notes note class science chapter unit lesson page part parts small large simple ways way home thing
things through tiny kind type types example examples important called also mainly usually often help helps later begins""".split())


class DocumentError(ValueError):
    pass


def _clean(text):
    text = text.replace("­", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)          # join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _is_heading(line):
    l = line.strip()
    if not (3 <= len(l) <= 70) or l.endswith((".", ",", ";", ":")) and not re.match(r"^\d+(\.\d+)*\.?\s", l):
        return False
    words = l.split()
    if len(words) > 9:
        return False
    if re.match(r"^(chapter|unit|section|lesson|part)\b", l, re.I) or re.match(r"^\d+(\.\d+)*\.?\s+[A-Z]", l):
        return True
    if l.isupper() and len(words) <= 7:
        return True
    caps = sum(w[:1].isupper() for w in words if len(w) > 3)
    return caps >= max(1, len([w for w in words if len(w) > 3]) - 1) and len(words) <= 7


def sentences_of(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", " ".join(text.split()))
    return [p.strip() for p in parts if 6 <= len(p.split()) <= 45]


def _key_terms(text, headings, n=40):
    words = re.findall(r"[A-Za-z][A-Za-z-]{2,}", text)
    low = [w.lower() for w in words if w.lower() not in STOP]
    cnt = Counter(low)
    # multi-word terms that repeat (e.g. "light reactions", "Calvin cycle")
    bi = Counter()
    for seg in re.split(r"[.,;:!?()\n]", text):          # word pairs never cross punctuation
        ts = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z-]{2,}", seg)]
        bi.update(f"{a} {b}" for a, b in zip(ts, ts[1:]) if a not in STOP and b not in STOP)
    terms = [t for t, c in bi.most_common(30) if c >= 2]
    for h in headings:
        for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", h):
            if w.lower() not in STOP:
                cnt[w.lower()] += 3
    body = Counter(low)
    terms += [w for w, c in cnt.most_common(n * 2) if body[w] >= 2 and len(w) > 3]
    out = []
    for t in terms:
        if not any(t in o or o in t for o in out):
            out.append(t)
    return out[:n]


def extract(pdf_bytes: bytes, filename: str = "notes.pdf") -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise DocumentError("PDF support is not installed. Run: py -3.11 -m pip install pypdf") from e
    if not pdf_bytes[:5] == b"%PDF-":
        raise DocumentError("This file is not a PDF.")
    if len(pdf_bytes) > 30 * 2**20:
        raise DocumentError("This PDF is larger than 30 MB. Please upload a smaller file.")
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [_clean(p.extract_text() or "") for p in reader.pages[:120]]
    except Exception as e:
        raise DocumentError(f"Could not read this PDF ({type(e).__name__}).") from e
    words = sum(len(p.split()) for p in pages)
    if words < 80:
        raise DocumentError("This PDF has almost no readable text. If it is a scanned image, please upload a "
                            "text PDF (scanned pages need OCR, which is not supported offline).")
    sections, cur = [], {"title": "Introduction", "page": 1, "text": []}
    for pi, page in enumerate(pages, 1):
        for line in page.split("\n"):
            if _is_heading(line):
                title = re.sub(r"^\d+(\.\d+)*\.?\s*", "", line.strip())[:70]
                if cur["text"]:
                    sections.append(cur)
                    cur = {"title": title, "page": pi, "text": []}
                else:                       # two headings in a row: the more specific one wins
                    cur["title"], cur["page"] = title, pi
            elif line.strip():
                cur["text"].append(line.strip())
    if cur["text"]:
        sections.append(cur)
    # merge tiny sections into the previous one
    merged = []
    for s in sections:
        body = " ".join(s["text"])
        if merged and len(body.split()) < 40:
            merged[-1]["body"] += " " + body
        else:
            merged.append({"title": s["title"], "page": s["page"], "body": body})
    chunks = []
    for si, s in enumerate(merged):
        sent = sentences_of(s["body"])
        s["id"], s["words"] = si, len(s["body"].split())
        buf = []
        for x in sent:
            buf.append(x)
            if sum(len(b) for b in buf) > 700:
                chunks.append({"id": len(chunks), "section": si, "page": s["page"], "text": " ".join(buf)})
                buf = []
        if buf:
            chunks.append({"id": len(chunks), "section": si, "page": s["page"], "text": " ".join(buf)})
    full = " ".join(s["body"] for s in merged)
    doc_id = hashlib.sha1(pdf_bytes).hexdigest()[:12]
    doc = {"id": doc_id, "name": filename[:120], "pages": len(pages), "words": words,
           "sections": [{"id": s["id"], "title": s["title"], "page": s["page"], "words": s["words"]} for s in merged],
           "chunks": chunks, "key_terms": _key_terms(full, [s["title"] for s in merged]),
           "sentences": [{"text": x, "section": c["section"], "page": c["page"]}
                         for c in chunks for x in sentences_of(c["text"])]}
    d = DOCS / doc_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.pdf").write_bytes(pdf_bytes)
    (d / "doc.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return doc


def load(doc_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{12}", doc_id or ""):
        raise DocumentError("bad document id")
    f = DOCS / doc_id / "doc.json"
    if not f.exists():
        raise DocumentError("document not found; please upload it again")
    return json.loads(f.read_text(encoding="utf-8"))


def summary(doc):
    return {k: doc[k] for k in ("id", "name", "pages", "words", "sections")} | {"key_terms": doc["key_terms"][:12]}
