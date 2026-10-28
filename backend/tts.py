"""Stage 4b: local text-to-speech. Each beat becomes one audio clip; its length sets the timing."""
import logging
import re
import threading
import numpy as np

from . import config

log = logging.getLogger("tts")
_lock = threading.Lock()
_kokoro = None
_parler = None


def _clean_for_speech(text: str) -> str:
    text = text.replace("`", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _resample(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr == config.SAMPLE_RATE:
        return audio.astype(np.float32)
    n = int(len(audio) * config.SAMPLE_RATE / sr)
    x_old = np.linspace(0, 1, len(audio), endpoint=False)
    x_new = np.linspace(0, 1, n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def _trim(audio: np.ndarray, thresh=0.01) -> np.ndarray:
    idx = np.where(np.abs(audio) > thresh)[0]
    if len(idx) == 0:
        return audio
    a, b = max(0, idx[0] - 600), min(len(audio), idx[-1] + 1200)
    return audio[a:b]


# ---------- engines ----------

def _kokoro_say(text, lang, gender, speed):
    global _kokoro
    from kokoro_onnx import Kokoro
    if _kokoro is None:
        # look for the files now (not at start-up), so files added later are found
        onnx = next((config.MODELS_DIR / n for n in ("kokoro-v1.0.int8.onnx", "kokoro-v1.0.onnx", "kokoro-v1.0.fp16.onnx")
                     if (config.MODELS_DIR / n).exists()), None)
        if onnx is None:
            raise FileNotFoundError(f"Voice model missing: put kokoro-v1.0.int8.onnx in the folder {config.MODELS_DIR}")
        if not config.KOKORO_VOICES.exists():
            raise FileNotFoundError(f"Voice file missing: put voices-v1.0.bin in the folder {config.MODELS_DIR}")
        _kokoro = Kokoro(str(onnx), str(config.KOKORO_VOICES))
    L = config.LANGS[lang]
    voice = L["voices"].get(gender, list(L["voices"].values())[0])
    samples, sr = _kokoro.create(text, voice=voice, speed=speed, lang=L["kokoro_lang"])
    return np.asarray(samples, dtype=np.float32), sr


PARLER_DESC = {
    "female": "A female speaker delivers a clear, friendly lesson at a moderate pace. "
              "The recording is very clear and close-sounding with no background noise.",
    "male": "A male speaker delivers a clear, friendly lesson at a moderate pace. "
            "The recording is very clear and close-sounding with no background noise.",
}


def _parler_say(text, lang, gender, speed):
    global _parler
    import torch
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer
    if _parler is None:
        m = ParlerTTSForConditionalGeneration.from_pretrained(config.PARLER_MODEL)
        t = AutoTokenizer.from_pretrained(config.PARLER_MODEL)
        dt = AutoTokenizer.from_pretrained(m.config.text_encoder._name_or_path)
        _parler = (m, t, dt)
    m, t, dt = _parler
    with torch.no_grad():
        d = dt(PARLER_DESC.get(gender, PARLER_DESC["female"]), return_tensors="pt")
        p = t(text, return_tensors="pt")
        gen = m.generate(input_ids=d.input_ids, attention_mask=d.attention_mask,
                         prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
    audio = gen.cpu().numpy().squeeze().astype(np.float32)
    sr = m.config.sampling_rate
    return audio, sr  # Parler speed: change the description text ("slow"/"fast pace") if needed


def _silent_say(text, lang, gender, speed):
    # ~2.6 words/s English; Indic scripts estimated by characters
    words = len(text.split())
    secs = max(1.2, words / 2.6 / speed) if lang == "en" else max(1.2, len(text) / 13 / speed)
    return np.zeros(int(secs * config.SAMPLE_RATE), dtype=np.float32), config.SAMPLE_RATE


ENGINES = {"kokoro": _kokoro_say, "parler": _parler_say, "silent": _silent_say}


def engine_for(lang: str) -> str:
    return config.TTS_OVERRIDE or config.LANGS[lang]["tts"]


def say(text: str, lang: str, gender: str = "female", speed: float = 1.0) -> np.ndarray:
    """Returns mono float32 audio at config.SAMPLE_RATE."""
    text = _clean_for_speech(text)
    eng = engine_for(lang)
    with _lock:  # models are not thread-safe; one clip at a time keeps RAM low
        audio, sr = ENGINES[eng](text, lang, gender, speed)
    audio = _resample(audio, sr)
    if eng != "silent":
        audio = _trim(audio)
        peak = float(np.max(np.abs(audio))) or 1.0
        audio = audio / peak * 0.9
    return audio
