"""Build the ready-made fallback lessons BEFORE the demo, so a model failure never shows an error.

Start the server first (MP4 export renders through it), then in a second window:
    py -3.11 -m backend.prebake en hi mr                     all topics, beginner, 60 s, audio only
    py -3.11 -m backend.prebake en hi --levels beginner intermediate --seconds 45 60
    add --mp4 to also pre-render the MP4s (slower)
The fallback is used automatically when the request matches (topic, level, length, language,
female voice, speed 1.0); other combinations are built on the spot from the same lesson.
"""
import sys
import time

from . import config, knowledge, pipeline

if __name__ == "__main__":
    args = sys.argv[1:]
    mp4 = "--mp4" in args
    langs, levels, secs, mode = [], [], [], "langs"
    for a in args:
        if a in ("--levels", "--seconds"):
            mode = a[2:]
        elif a.startswith("--"):
            continue
        elif mode == "levels":
            levels.append(a)
        elif mode == "seconds":
            secs.append(int(a))
        else:
            langs.append(a)
    langs, levels, secs = langs or ["en", "hi"], levels or ["beginner"], secs or [60]
    t0 = time.time()
    for name in knowledge.all_topics():
        for lang in langs:
            if lang not in config.LANGS:
                print(f"[skip] unknown language {lang}")
                continue
            for level in levels:
                for s in secs:
                    try:
                        job = pipeline.prebake(name, lang, level, s, mp4=mp4)
                        print(f"[ok] {name} / {lang} / {level} / {s}s: {job.timings}", flush=True)
                    except Exception as e:
                        print(f"[FAILED] {name} / {lang} / {level} / {s}s: {type(e).__name__}: {e}", flush=True)
    print(f"done in {time.time() - t0:.0f}s")
