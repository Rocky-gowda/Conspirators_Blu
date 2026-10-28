"""Offline spelling correction with confidence levels (SymSpell + the app's subject vocabulary).

Rules, in order:
  * never touch: short words, stop words, ALL-CAPS acronyms, names, real English words ("pumps" stays)
  * subject words first ("pyton" -> python, "algoritm" -> algorithm, "pyhsics" -> physics): auto-fix
  * general English only when very sure ("blak" -> black); otherwise only *suggest*, never rewrite
    (so "virat" is not turned into "viral", "kohli" not into "kohl")
  * missing spaces: "binarysearch" -> "binary search"; split words: "photo synthesis" -> photosynthesis
  * split misspellings ("phito systhse") are too uncertain to rewrite: returned as "did you mean photosynthesis?"

If symspellpy is not installed, falls back to the subject vocabulary only (difflib), so nothing breaks.
"""
import difflib
import os

try:
    import symspellpy
    from symspellpy import SymSpell, Verbosity
except Exception:                     # pragma: no cover - optional dependency
    symspellpy = None

_state = {}
MIN_COUNT = 20_000          # words rarer than this in the frequency list are not treated as English words


def _load(domain_vocab):
    key = len(domain_vocab)
    if _state.get("key") == key:
        return _state
    _state.clear()
    _state["key"] = key
    _state["domain"] = sorted(domain_vocab)
    _state["domain_set"] = set(domain_vocab)
    if symspellpy is None:
        _state["general"] = None
        return _state
    d = os.path.dirname(symspellpy.__file__)
    # general English: 1-letter fixes only, common words only (automatic fixes need distance 1 anyway;
    # subject words keep 2-letter fixes through the small subject dictionary below). ~5x less memory.
    g = SymSpell(max_dictionary_edit_distance=1, prefix_length=7)
    with open(os.path.join(d, "frequency_dictionary_en_82_765.txt"), encoding="utf-8") as f:
        for line in f:
            w, _, c = line.partition(" ")
            if c and int(c) >= MIN_COUNT:
                g.create_dictionary_entry(w, int(c))
    dom = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    for w in domain_vocab:
        if w.isalpha() and len(w) > 2:
            dom.create_dictionary_entry(w, 1)
            if w not in g.words:          # subject words are real words too
                g.create_dictionary_entry(w, 1_000_000)
    _state["general"], _state["dom"] = g, dom
    return _state


def is_word(w, st):
    lw = w.lower()
    if lw in st["domain_set"]:
        return True
    g = st.get("general")
    return bool(g) and g.words.get(lw, 0) >= MIN_COUNT


def fix_word(w, st, protected=()):
    """-> (replacement or None, confidence 'high' | 'suggest' | None, source 'domain' | 'general' | None)."""
    lw = w.lower()
    if len(lw) < 4 or not lw.isalpha() or (w.isupper() and len(w) <= 6) or lw in protected or is_word(lw, st):
        return None, None, None
    g = st.get("general")
    if g is None:                                          # fallback: subject words only
        m = difflib.get_close_matches(lw, st["domain"], n=1, cutoff=0.85 if len(lw) <= 5 else 0.8)
        return (m[0], "high", "domain") if m else (None, None, None)
    max_d = 2 if len(lw) >= 8 else 1        # 2-letter fixes only for long words ("cholas" must not become "holes")
    r = st["dom"].lookup(lw, Verbosity.CLOSEST, max_d)
    if r:
        return r[0].term, "high", "domain"
    r = g.lookup(lw, Verbosity.CLOSEST, 1)
    if not r:
        return None, None, None
    best, runner = r[0], (r[1].count if len(r) > 1 else 1)
    if best.distance == 1 and best.count >= 20_000_000 and best.count >= 10 * runner:
        return best.term, "high", "general"
    return best.term, "suggest", "general"


def split_glued(w, st):
    """'binarysearch' -> 'binary search' (only pure space insertions into known words)."""
    g = st.get("general")
    lw = w.lower()
    if g is None or len(lw) < 8 or is_word(lw, st):
        return None
    parts = g.word_segmentation(lw).corrected_string.split()
    if len(parts) < 2 or "".join(parts) != lw or any(len(p) < 3 for p in parts):
        return None
    if not any(p in st["domain_set"] for p in parts) or not all(is_word(p, st) for p in parts):
        return None
    return " ".join(parts)


def join_pair(a, b, st, fa=None, fb=None):
    """Two words that are really one subject word -> (word, confidence).
    fa / fb: single-word fixes already found for a / b (tried as well: "phito"+"systhse")."""
    joined = (a + b).lower()
    if len(joined) < 8:
        return None, None
    if joined in st["domain_set"]:
        return joined, "high"
    if is_word(a, st) or is_word(b, st):
        return None, None                 # a real word next to another word: not a broken-up word
    pool = [w for w in st["domain"] if len(w) >= 8]
    best, ratio = None, 0.0
    for cand in {joined, (fa or a).lower() + (fb or b).lower()}:
        m = difflib.get_close_matches(cand, pool, n=1, cutoff=0.62)
        if m:
            r = difflib.SequenceMatcher(None, cand, m[0]).ratio()
            if r > ratio:
                best, ratio = m[0], r
    if not best:
        return None, None
    return best, ("high" if ratio >= 0.85 else "suggest")


def correct(tokens, domain_vocab, protected=(), stop=()):
    """tokens: words in order. Returns (new_tokens, fixes [[old, new]], suggestions).

    suggestions: [{"word": new, "from": old, "how": "join" | "word"}].
    Two or more unknown words in a row usually make a name ("rahul dravid"): general-English fixes and
    suggestions are not applied to them (subject-word fixes still are)."""
    st = _load(domain_vocab)
    protected = {p.lower() for p in protected}
    skip = lambda t: t.lower() in stop or t.lower() in protected
    info = [(None, None, None) if skip(t) else fix_word(t, st, protected) for t in tokens]
    unknown = [not skip(t) and t.isalpha() and len(t) >= 3 and not is_word(t, st) for t in tokens]

    def name_like(i):
        near = [j for j in (i - 1, i + 1) if 0 <= j < len(tokens)]
        return any(unknown[j] and info[j][2] != "domain" for j in near)

    out, fixes, suggest = [], [], []
    i = 0
    while i < len(tokens):
        w = tokens[i]
        if skip(w):
            out.append(w)
            i += 1
            continue
        if i + 1 < len(tokens) and not skip(tokens[i + 1]) \
                and not (info[i][2] == "domain" and info[i + 1][2] == "domain"):
            jw, conf = join_pair(w, tokens[i + 1], st, info[i][0], info[i + 1][0])
            if jw and conf == "high":
                fixes.append([f"{w} {tokens[i + 1]}", jw])
                out.append(jw)
                i += 2
                continue
            if jw and conf == "suggest":
                suggest.append({"word": jw, "from": f"{w} {tokens[i + 1]}", "how": "join"})
                out.extend([w, tokens[i + 1]])
                i += 2
                continue
        sp = split_glued(w, st)
        if sp:
            fixes.append([w, sp])
            out.extend(sp.split())
            i += 1
            continue
        f, conf, src = info[i]
        if src == "general" and name_like(i):
            f = None
        if f and conf == "high":
            fixes.append([w, f])
            out.append(f)
        else:
            if f and conf == "suggest":
                suggest.append({"word": f, "from": w, "how": "word"})
            out.append(w)
        i += 1
    return out, fixes, suggest


def available():
    return symspellpy is not None
