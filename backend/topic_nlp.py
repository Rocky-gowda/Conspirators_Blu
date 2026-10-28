"""Stage 1b: understand what the learner typed, before the LLM sees it (all offline, no models).

  * cleans the text and fixes typos of subject words ("photosynthsis" -> "photosynthesis")
  * detects the subject (programming, biology, physics, chemistry, math, earth, history, general)
  * finds key terms and the closest topic in the offline knowledge base
  * returns facts from that topic, so the LLM is grounded in checked information
"""
import difflib
import math
import re

from . import knowledge, spelling

DOMAIN_WORDS = {
    "programming": "computer computers software python java javascript code coding program programming function functions loop loops variable variables "
                   "array arrays list lists string strings algorithm algorithms recursion recursive class classes object objects "
                   "sort sorting search searching stack queue tree graph database sql html css api compiler debug bug "
                   "integer boolean dictionary hash pointer complexity binary",
    "biology": "cell cells plant plants animal animals heart blood lungs body organ organs photosynthesis respiration dna gene genes "
               "evolution digestion digestive enzyme enzymes protein proteins bacteria virus immune nerve nervous brain muscle "
               "kidney leaf leaves chlorophyll ecosystem species reproduction mitosis meiosis",
    "physics": "force forces motion newton gravity energy work power velocity acceleration speed mass momentum friction "
               "electricity electric current voltage resistance circuit magnet magnetic wave waves light sound heat "
               "pressure ohm lens mirror refraction reflection space universe star stars galaxy galaxies orbit astronomy "
               "black hole holes relativity quantum nuclear atom",
    "chemistry": "atom atoms molecule molecules element elements compound compounds reaction reactions acid acids base bases "
                 "ph salt salts chemical bond bonds periodic table electron electrons proton neutron oxidation reduction "
                 "metal metals solution mixture catalyst",
    "math": "math maths mathematics number numbers fraction fractions decimal percent percentage algebra equation equations "
            "geometry triangle triangles circle angle angles area volume perimeter theorem pythagoras pythagorean "
            "probability statistics mean median calculus derivative integral matrix prime factor square root",
    "earth": "earth water cycle rain cloud clouds weather climate volcano volcanoes earthquake earthquakes rock rocks soil "
             "river rivers ocean oceans planet planets solar sun moon season seasons atmosphere erosion tides",
    "history": "history war wars empire empires king kings queen revolution independence freedom movement colonial ancient "
               "medieval civilization civilisation dynasty constitution gandhi british mughal battle century treaty",
}
DOMAIN_SETS = {d: set(w.split()) for d, w in DOMAIN_WORDS.items()}

STOP = set("""a an the is are was were be been of to in on for and or how what why when where which who does do did
explain tell me about show teach learn learning lesson please work works working make makes made use uses using
can could would should with without into from by at as it its this that these those your my our their simple
basic basics intro introduction understand understanding mean means meaning""".split())


def _vocab():
    v = knowledge.vocabulary()
    for s in DOMAIN_SETS.values():
        v |= s
    return sorted(v)


# everyday words that look like subject words; never "correct" these
COMMON = set("""plan time part step life real many more most some them then than good best fast long high rule take
give find face fact form note nice word page home game play test type kind list line read code call cool easy hard
help idea look move need open real sort talk tree wave work year area data unit mass heat""".split())


def _fix_word(w, vocab, vocab_set):
    lw = w.lower()
    if len(lw) < 4 or lw in vocab_set or lw in STOP or lw in COMMON:
        return w
    m = difflib.get_close_matches(lw, vocab, n=1, cutoff=0.85 if len(lw) <= 5 else 0.8)
    return m[0] if m else w


# ---------------------------------------------------------------- named entities, intent, relevance

PLACES = set("""india china japan nepal bhutan bangladesh pakistan sri lanka america usa canada mexico brazil russia
france germany italy spain england britain uk australia africa egypt kenya europe asia antarctica arctic delhi mumbai
kolkata chennai bengaluru bangalore hyderabad pune jaipur goa kerala karnataka tamil nadu maharashtra gujarat punjab
rajasthan bihar odisha assam telangana andhra pradesh bengal kashmir himalaya himalayas ganga ganges yamuna everest
sahara amazon nile pacific atlantic indian ocean london paris tokyo moscow beijing new north south east west
taj mahal red fort qutub minar charminar gateway hampi konark ajanta ellora eiffel tower great wall""".split())
PLACE_WORDS = set("fort palace temple tower bridge wall dam lake river mount mountain city state island valley "
                  "desert forest park museum minar mahal gate gateway".split())
ORG_WORDS = set("university college company corporation organisation organization institute bank party ministry "
                "council union nations isro nasa un unesco who rbi bcci iit iisc drdo".split())
PERSON_HINTS = set("who biography life born died founder scientist king queen leader player cricketer actor author poet".split())

BROAD = {
    "artificial intelligence": ["What is machine learning?", "How does a chatbot understand questions?", "What is a neural network?"],
    "ai": ["What is machine learning?", "How does a chatbot understand questions?", "What is a neural network?"],
    "machine learning": ["What is supervised learning?", "How does a model learn from examples?", "What is a decision tree?"],
    "science": ["What is photosynthesis?", "Newton's laws of motion", "The water cycle"],
    "physics": ["Newton's laws of motion", "Explain Ohm's law", "What is gravity?"],
    "chemistry": ["What are acids and bases?", "What is an atom?", "What is a chemical reaction?"],
    "biology": ["What is photosynthesis?", "How does the human heart work?", "What is a cell?"],
    "maths": ["The Pythagorean theorem", "What are fractions?", "What is probability?"],
    "math": ["The Pythagorean theorem", "What are fractions?", "What is probability?"],
    "mathematics": ["The Pythagorean theorem", "What are fractions?", "What is probability?"],
    "history": ["India's road to independence", "The Mughal empire", "The French Revolution"],
    "computer": ["How does a computer store data?", "How does a Python loop work?", "What is an algorithm?"],
    "computers": ["How does a computer store data?", "How does a Python loop work?", "What is an algorithm?"],
    "programming": ["How does a Python loop work?", "What is a variable?", "Binary search"],
    "coding": ["How does a Python loop work?", "What is a variable?", "Binary search"],
    "electricity": ["Explain Ohm's law", "What is electric current?", "Series and parallel circuits"],
    "space": ["How does the solar system work?", "What is gravity?", "Why does the moon have phases?"],
    "environment": ["The water cycle", "What is global warming?", "What is an ecosystem?"],
    "internet": ["How does the internet send data?", "What is a web browser?", "What is an IP address?"],
    "health": ["How does the human heart work?", "What is a balanced diet?", "How do vaccines work?"],
    "economics": ["What is supply and demand?", "What is inflation?", "What is money?"],
    "geography": ["The water cycle", "Why do we have seasons?", "How are mountains formed?"],
    "english": ["What is a noun?", "Tenses in English", "How to write a paragraph"],
}

# letter-pair model of English-like words, to spot random typing ("asdf qwer") offline
_LM = {}


def _train_lm():
    if _LM:
        return _LM
    corpus = " ".join(DOMAIN_WORDS.values()) + " " + " ".join(STOP) + " " + " ".join(COMMON) + " " + " ".join(PLACES)
    corpus += """ the quick brown fox jumps over the lazy dog people often learn better when they see ideas move
    step by step students teachers school class question answer story world country city river mountain music art
    sport cricket football game player team match history science nature animal family friend food water house
    india machine learning artificial intelligence democracy government election parliament constitution economy money
    market business company computer internet phone network data information knowledge language english hindi"""
    for kb in knowledge.all_topics().values():
        corpus += " " + kb["keywords"] + " " + " ".join(kb["facts"])
        for sc in kb["lesson"]["scenes"]:
            corpus += " " + " ".join(b["text"] for b in sc["narration"])
    GENERAL.update(re.findall(r"[a-z]+", corpus.lower()))
    corpus += " " + NAMES
    pairs, firsts = {}, {}
    for w in re.findall(r"[a-z]+", corpus.lower()):
        w = "^" + w + "$"
        for a, b in zip(w, w[1:]):
            pairs[a + b] = pairs.get(a + b, 0) + 1
            firsts[a] = firsts.get(a, 0) + 1
    _LM.update({k: math.log((v + 0.1) / (firsts[k[0]] + 2.8)) for k, v in pairs.items()})
    _LM["_floor"] = math.log(0.1 / 1000)
    return _LM


NAMES = """kumar sharma singh virat kohli sachin tendulkar gandhi nehru abdul kalam rabindranath tagore
mahatma jawaharlal indira modi ambedkar bhagat vivekananda ramanujan raman bose sarojini naidu kalpana chawla
einstein newton curie darwin galileo tesla edison shakespeare dhoni rohit sindhu mary kom neeraj chopra"""
NAME_SET = set(NAMES.split())
GENERAL = set()          # ordinary English words seen in the training text (filled by _train_lm)
KEYBOARD = ("qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890")


def gibberish(w: str) -> bool:
    """Random typing: keyboard runs, no vowels, long consonant runs, or a very un-English letter pattern."""
    lw = w.lower()
    if len(lw) < 3:
        return False
    if any(lw[i:i + 3] in row for row in KEYBOARD for i in range(len(lw) - 2)):
        return True
    if not re.search(r"[aeiouy]", lw) or re.search(r"[^aeiouy]{5,}", lw) or re.search(r"(.)\1\1", lw):
        return True
    return wordlike(lw) < -4.6


def wordlike(w: str) -> float:
    """Average letter-pair log-probability: about -2 for real words, below -3.6 for random typing."""
    lm = _train_lm()
    w = "^" + w.lower() + "$"
    ps = [lm.get(a + b, lm["_floor"]) for a, b in zip(w, w[1:])]
    return sum(ps) / len(ps)


def _entities(raw: str):
    """Capitalised names (Virat Kohli, New Delhi), acronyms (ISRO) and known places."""
    _train_lm()
    toks = [re.sub(r"'s$", "", t) for t in re.findall(r"[A-Za-z][A-Za-z.'-]*", raw)]
    ents, run = [], []
    for i, t in enumerate(toks + ["."]):
        cap = t[:1].isupper() and t.lower() not in STOP and not (i == 0 and t.lower() in DOMAIN_SETS_ALL)
        if cap and t != ".":
            run.append(t)
        else:
            if run and (len(run) >= 2 or i > 1 or run[0].isupper() or run[0].lower() in PLACES):
                ents.append(" ".join(run))
            run = []
    # lowercase names that we know ("virat kohli", "sachin tendulkar")
    low_toks = [t.lower() for t in toks]
    covered = {w.lower() for e in ents for w in e.split()}
    run = []
    for t in low_toks + ["."]:
        if t in NAME_SET and t not in covered:
            run.append(t)
        else:
            if run:
                ents.append(" ".join(w.capitalize() for w in run))
            run = []
    out = []
    for e in ents:
        low = e.lower()
        words = low.split()
        if all(w in PLACES or w in PLACE_WORDS for w in words) or (words[-1] in PLACE_WORDS and len(words) > 1):
            kind = "place"
        elif any(w in NAME_SET for w in words):
            kind = "person"
        elif any(w in ORG_WORDS for w in words) or (e.isupper() and len(e) <= 6):
            kind = "organisation"
        elif len(words) <= 4 and not any(w in DOMAIN_SETS_ALL for w in words) \
                and not all(w in GENERAL for w in words) \
                and not all(any(w in kb["_kw"] for kb in knowledge.all_topics().values()) for w in words):
            kind = "person"
        else:
            continue
        out.append({"text": e, "type": kind})
    return out


DOMAIN_SETS_ALL = set().union(*DOMAIN_SETS.values())


def _intent(low: str):
    if re.match(r"^(who (is|was)|biography)", low):
        return "about a person"
    if re.search(r"\b(difference|compare|vs|versus)\b", low):
        return "compare"
    if re.match(r"^(how|why)\b", low):
        return "explain how/why"
    if re.match(r"^(what (is|are)|define|meaning)\b", low):
        return "define"
    return "explain"


def analyze(topic: str) -> dict:
    """Structured understanding of the request, used by every later stage."""
    raw = " ".join(str(topic).split()).strip(" \"'")
    vocab = _vocab()
    vocab_set = set(vocab)
    ents = _entities(raw)
    ent_words = {w.lower() for e in ents for w in e["text"].split()}
    toks = re.findall(r"[A-Za-z]+", raw)
    # capitalised words after the first are names or proper nouns: never "corrected"
    protected = ent_words | NAME_SET | {t.lower() for t in toks[1:] if t[:1].isupper()}
    try:
        _, fixes, spell_sugg = spelling.correct(toks, vocab_set, protected, STOP | COMMON)
    except Exception:                                    # spelling must never stop a lesson
        fixes, spell_sugg = [], []
    clean = raw
    for old, new in fixes:                               # apply fixes to the original text (keeps punctuation)
        pat = r"\b" + r"\s+".join(map(re.escape, old.split())) + r"\b"
        clean = re.sub(pat, new, clean, count=1, flags=re.I)
    clean = clean.strip()
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", clean)]
    content = [w for w in words if w not in STOP]
    wset = set(content) | {w[:-1] for w in content if w.endswith("s") and len(w) > 3}

    # --- subject (domain)
    scores = {d: len(wset & s) for d, s in DOMAIN_SETS.items()}
    from . import retrieval
    key_terms = list(dict.fromkeys(w for w in content if len(w) > 2))[:6]
    known = [w for w in content if w in vocab_set or w in COMMON]
    domain_hint = []
    best_dom = max(scores, key=scores.get)
    if scores[best_dom]:
        domain_hint = [w for w in content if w in DOMAIN_SETS[best_dom]]
    ret = retrieval.retrieve(clean, key_terms, [f[1] for f in fixes] + known, domain_hint)
    kb = knowledge.get(ret["topic"]) if ret["topic"] else None
    if kb:
        scores[kb["domain"]] = scores.get(kb["domain"], 0) + 2
    domain = max(scores, key=scores.get)
    if scores[domain] == 0:
        domain = "general"

    # --- what kind of topic, and is it a sensible lesson request?
    person = [e for e in ents if e["type"] == "person"]
    kind = "concept"
    if ents and not kb and not scores.get(best_dom):
        kind = ents[0]["type"]
    if person:
        kind = "person"
    if re.match(r"^(who (is|was))\b", clean.lower()) or (person and set(content) & PERSON_HINTS):
        kind = "person"
    related = ret.get("related")
    if kind == "person" and kb:
        names = {w.lower() for e in person for w in e["text"].split()}
        if not names & set(retrieval.tokens(kb["lesson"]["title"])):
            # a lesson about Gandhi is not the independence lesson: keep it only as related background
            related, kb = kb["id"], None
            ret = dict(ret, topic=None, facts=[])
    if kind == "person" and not kb:
        domain = "person"
    gib = [w for w in content if w not in vocab_set and w not in COMMON and w not in ent_words and gibberish(w)]
    core = " ".join(words)
    for lead in ("what is ", "what are ", "explain ", "tell me about ", "learn ", "about ", "intro to ", "introduction to ", "the "):
        if core.startswith(lead):
            core = core[len(lead):]
    status, message, suggestions = "ok", "", []
    letters = sum(c.isalpha() for c in raw)
    if letters < 2:
        status, message = "invalid", "Please type a topic in words, for example: How does a Python loop work?"
    elif content and len(gib) == len(content):
        status, message = "invalid", ("This doesn't look like a topic I can teach. "
                                      "Please type a subject, for example: What is photosynthesis?")
    elif gib and len(gib) >= len(content) / 2:
        kw = [w for w in content if w not in gib]
        status = "unclear"
        message = "Some of this looks like random typing. I found: " + ", ".join(kw) if kw else ""
        if kb:
            suggestions = [kb["lesson"]["title"]]
        elif kw:
            suggestions = [f"What is {' '.join(kw)}?"]
    elif spell_sugg:
        # not sure enough to rewrite: ask ("phito systhse" -> "Did you mean photosynthesis?")
        guess = clean
        for sg in spell_sugg:
            pat = r"\b" + r"\s+".join(map(re.escape, sg["from"].split())) + r"\b"
            guess = re.sub(pat, sg["word"], guess, count=1, flags=re.I)
        status = "unclear"
        message = "Did you mean " + ", ".join(f"“{sg['word']}”" for sg in spell_sugg) + "? Pick it, or continue as typed."
        suggestions = [guess]
    elif core in BROAD:
        status = "broad"
        message = f"“{clean}” is a very big subject. Pick one part for a short lesson, or continue as typed."
        suggestions = BROAD[core]
    if kb and status == "ok" and ret["score"] < 0.75 and kb["lesson"]["title"].lower() not in clean.lower():
        # a weak match is shown as a suggestion only; it is not assumed to be what the learner meant
        pass
    if status == "ok" and gib:              # drop stray random words before the AI sees the topic
        for g in gib:
            clean = re.sub(rf"\b{re.escape(g)}\b", "", clean, flags=re.I)
            fixes.append([g, "(removed)"])
        clean = " ".join(clean.split())
        key_terms = [k for k in key_terms if k not in gib]
    if kind == "concept" and not kb and content and not any(w in vocab_set or w in GENERAL for w in content):
        kind = "unknown"      # probably a name or a local term: the AI is told it may be a person, place or thing
    highlights = [w for w in key_terms if w in vocab_set or w in ent_words] or key_terms[:3]
    return {
        "original": raw,
        "topic": clean or raw,
        "fixes": fixes,
        "domain": domain,
        "kind": kind,
        "intent": _intent(clean.lower()),
        "entities": ents,
        "key_terms": key_terms,
        "highlights": highlights,
        "status": status,
        "message": message,
        "suggestions": suggestions,
        "kb": kb["id"] if kb else None,
        "kb_score": ret["score"],
        "retrieval": {"method": ret["method"], "attempts": ret["attempts"]},
        "facts": ret["facts"],
        "related": related,
        "grounded": bool(kb),
    }


def basic(topic: str) -> dict:
    """Minimal understanding used only if the full analysis fails: cleaned text, no knowledge match."""
    raw = " ".join(str(topic).split()).strip(" \"'")
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", raw)]
    return {"original": raw, "topic": raw, "fixes": [], "domain": "general", "kind": "unknown", "intent": "explain",
            "entities": [], "key_terms": [w for w in words if w not in STOP][:6], "highlights": [],
            "status": "ok" if any(c.isalpha() for c in raw) else "invalid", "message": "", "suggestions": [],
            "kb": None, "kb_score": 0, "retrieval": {"method": "none", "attempts": []}, "facts": [], "related": None,
            "grounded": False}
