"""Builds the timeline: the voice comes first, and every scene lasts as long as its audio + a pause.

The timeline is the single source of truth for the browser player AND the MP4 exporter.

`Builder` adds scenes one at a time (so a lesson can start playing while the LLM is still writing
the next scene). Each scene gets its own audio clip; the full audio is the exact concatenation,
so the live player and the MP4 have identical timing.
"""
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config, tts

CLIP_CACHE = config.DATA / "clips"
SR = config.SAMPLE_RATE
LEAD = 0.4            # heading appears before the voice starts


def clip(text, lang, gender, speed) -> np.ndarray:
    """Audio for one sentence, cached on disk: editing one scene only re-voices what changed."""
    eng = tts.engine_for(lang)
    key = hashlib.sha1(f"{eng}|{lang}|{gender}|{speed}|{text}".encode()).hexdigest()[:16]
    f = CLIP_CACHE / f"{key}.wav"
    if f.exists():
        a, _ = sf.read(f, dtype="float32")
        return a
    a = tts.say(text, lang, gender, speed)
    CLIP_CACHE.mkdir(parents=True, exist_ok=True)
    sf.write(f, a, SR)
    return a


def _srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _encode_m4a(samples: np.ndarray, path: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-c:a", "aac", "-b:a", "96k", str(path)], input=samples.astype(np.float32).tobytes(), check=True)


class Builder:
    def __init__(self, out_dir: Path, meta: dict, gender="female", speed=1.0,
                 beat_gap=config.PAUSE_BETWEEN_BEATS, scene_gap=config.PAUSE_AFTER_SCENE):
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = dict(meta)          # title, level, language, domain, ...
        self.gender, self.speed = gender, speed
        self.beat_gap, self.scene_gap = beat_gap, scene_gap
        self.lang = self.meta["language"]
        self.scenes, self.audio, self.t = [], [], 0.0

    def estimate(self, scene) -> float:
        """Seconds this scene will take (voices it, which also fills the clip cache)."""
        d = LEAD + self.scene_gap
        for b in scene.narration:
            d += len(clip(b.text, self.lang, self.gender, self.speed)) / SR + self.beat_gap
        return d

    def add(self, scene, tail_pad: float = 0.0, beat_gap=None, scene_gap=None) -> dict:
        beat_gap = self.beat_gap if beat_gap is None else beat_gap
        scene_gap = self.scene_gap if scene_gap is None else scene_gap
        i = len(self.scenes)
        start = self.t
        parts = [np.zeros(int(LEAD * SR), np.float32)]
        t = start + LEAD
        beats = []
        for b in scene.narration:
            a = clip(b.text, self.lang, self.gender, self.speed)
            beats.append({"start": round(t, 3), "end": round(t + len(a) / SR, 3), "text": b.text, "focus": b.focus})
            parts += [a, np.zeros(int(beat_gap * SR), np.float32)]
            t += len(a) / SR + beat_gap
        parts.append(np.zeros(int((scene_gap + max(0.0, tail_pad)) * SR), np.float32))
        samples = np.concatenate(parts)
        self.t = start + len(samples) / SR          # exact clock: samples / rate
        data = scene.model_dump()
        data.pop("narration")
        audio_name = f"scene_{i}.m4a"
        _encode_m4a(samples, self.dir / audio_name)
        self.audio.append(samples)
        entry = {"index": i, "type": scene.type, "start": round(start, 3), "end": round(self.t, 3),
                 "data": data, "beats": beats, "audio": audio_name}
        self.scenes.append(entry)
        self._write(complete=False)
        return entry

    @property
    def duration(self):
        return self.t

    def _timeline(self, complete):
        L = config.LANGS[self.lang]
        return {**self.meta, "font": L["font"], "duration": round(self.t, 3), "complete": complete,
                "audio": "audio.m4a" if complete else None,
                "voice": {"gender": self.gender, "speed": self.speed, "engine": tts.engine_for(self.lang)},
                "scenes": self.scenes}

    def _write(self, complete):
        tmp = self.dir / "timeline.tmp.json"
        tmp.write_text(json.dumps(self._timeline(complete), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.dir / "timeline.json")     # atomic: the player never reads half a file

    def finalize(self, **meta) -> dict:
        self.meta.update(meta)
        audio = np.concatenate(self.audio) if self.audio else np.zeros(SR, np.float32)
        sf.write(self.dir / "audio.wav", audio, SR)
        _encode_m4a(audio, self.dir / "audio.m4a")
        srt, n = [], 1
        for sc in self.scenes:
            for b in sc["beats"]:
                srt.append(f"{n}\n{_srt_time(b['start'])} --> {_srt_time(b['end'])}\n{b['text']}\n")
                n += 1
        (self.dir / "captions.srt").write_text("\n".join(srt), encoding="utf-8")
        tl = self._timeline(True)
        self._write(complete=True)
        return tl


def paced_gaps(builder, scene, share):
    """Pauses for one scene so it fills its fair share of the target length (natural limits)."""
    est = builder.estimate(scene)
    short = share * 0.97 - est
    if est > share * 1.08:
        # this scene runs long: tighten its pauses (still natural) instead of cutting any explanation
        return {"beat_gap": 0.12, "scene_gap": 0.3}
    if short <= 0:
        return {}
    nb = max(1, len(scene.narration))
    extra_b = min(0.55, short * 0.5 / nb)
    extra_s = min(1.6, short - extra_b * nb)
    return {"beat_gap": builder.beat_gap + extra_b, "scene_gap": builder.scene_gap + max(0.0, extra_s)}


def fit_gaps(scenes, builder_kwargs, target, estimate_fn):
    """For lessons built all at once: stretch pauses (within natural limits) to approach the target."""
    speech = sum(estimate_fn(s) for s in scenes)
    short = target * 0.95 - speech
    if speech > target * 1.05:
        # running long: tighten the pauses (still natural) instead of cutting any explanation
        return {"beat_gap": 0.12, "scene_gap": 0.3}
    if short <= 0:
        return {}
    n_beats = sum(len(s.narration) for s in scenes)
    extra_beat = min(0.6, short * 0.6 / max(1, n_beats))
    extra_scene = min(1.0, (short - extra_beat * n_beats) / max(1, len(scenes)))
    return {"beat_gap": config.PAUSE_BETWEEN_BEATS + max(0.0, extra_beat),
            "scene_gap": config.PAUSE_AFTER_SCENE + max(0.0, extra_scene)}
