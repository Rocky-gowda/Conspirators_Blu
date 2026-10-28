"""All settings in one place. Change engines/models here, not in the code."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("BLU_DATA", ROOT / "data"))
LESSONS_DIR = DATA / "lessons"
MODELS_DIR = Path(os.environ.get("BLU_MODELS", ROOT / "models"))
FRONTEND = ROOT / "frontend"

VERSION = "v8"  # bump to invalidate the lesson cache

# ---- Planner (local LLM via Ollama) ----
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi4-mini")
# hybrid speed: the visual plan (rules, instant) decides the structure; a small fast model writes the sentences.
# BLU_SPEED=fast (default) uses FAST_MODEL when it is installed (`ollama pull qwen2.5:1.5b`), else OLLAMA_MODEL.
# BLU_SPEED=quality always uses OLLAMA_MODEL (slower, more detailed).
SPEED_MODE = os.environ.get("BLU_SPEED", "fast")
FAST_MODEL = os.environ.get("BLU_FAST_MODEL", "qwen2.5:1.5b")
# compact answer format: the visual plan fixes the scene types, the AI writes only headings, labels and
# sentences (about half the tokens of full scene objects). BLU_COMPACT=0 switches back to full objects.
COMPACT = os.environ.get("BLU_COMPACT", "1") != "0"
PLANNER_TIMEOUT_S = int(os.environ.get("BLU_PLAN_MAX_S", "300"))  # hard cap for one LLM answer
PLANNER_STALL_S = int(os.environ.get("BLU_STALL_S", "90"))   # give up only if the LLM sends nothing for this long
# a topic that strongly matches the checked notes plays the checked lesson at once (no AI wait, verified);
# set BLU_KB_FIRST=0 to always ask the AI
KB_FIRST = os.environ.get("BLU_KB_FIRST", "1") != "0"
KB_FIRST_MIN_SCORE = 0.75

# ---- Translation ----
INDICTRANS_MODEL = os.environ.get("INDICTRANS_MODEL", "ai4bharat/indictrans2-en-indic-dist-200M")
TRANSLATE_BEAMS = int(os.environ.get("BLU_BEAMS", "2"))  # 1 = fastest, 4 = best quality

# ---- Languages ----
# code -> settings. "tts" picks the engine in tts.py.
#   kokoro  : kokoro-onnx (en with Indian voice, hi)
#   parler  : AI4Bharat Indic Parler-TTS (ta, te, bn, mr ...)
#   silent  : no audio, duration estimated from text (for wiring/testing only)
LANGS = {
    "en": {"name": "English", "indictrans": None, "tts": "kokoro", "kokoro_lang": "en-us",
           "voices": {"female": "hf_alpha", "male": "hm_omega"}, "font": "Noto Sans"},
    "hi": {"name": "हिन्दी", "indictrans": "hin_Deva", "tts": "kokoro", "kokoro_lang": "hi",
           "voices": {"female": "hf_beta", "male": "hm_psi"}, "font": "Noto Sans Devanagari"},
    # Kannada, Marathi, Bengali, Tamil, Telugu: Kokoro with the Hindi voices + each language's own
    # pronunciation rules (espeak-ng). Fast on CPU and no extra download. Switch "tts" to "parler"
    # for AI4Bharat Indic Parler-TTS (more native accent, ~3.5 GB, much slower on CPU).
    "kn": {"name": "ಕನ್ನಡ", "indictrans": "kan_Knda", "tts": "kokoro", "kokoro_lang": "kn",
           "voices": {"female": "hf_alpha", "male": "hm_omega"}, "font": "Noto Sans Kannada"},
    "mr": {"name": "मराठी", "indictrans": "mar_Deva", "tts": "kokoro", "kokoro_lang": "mr",
           "voices": {"female": "hf_beta", "male": "hm_psi"}, "font": "Noto Sans Devanagari"},
    "bn": {"name": "বাংলা", "indictrans": "ben_Beng", "tts": "kokoro", "kokoro_lang": "bn",
           "voices": {"female": "hf_alpha", "male": "hm_omega"}, "font": "Noto Sans Bengali"},
    "ta": {"name": "தமிழ்", "indictrans": "tam_Taml", "tts": "kokoro", "kokoro_lang": "ta",
           "voices": {"female": "hf_alpha", "male": "hm_omega"}, "font": "Noto Sans Tamil"},
    "te": {"name": "తెలుగు", "indictrans": "tel_Telu", "tts": "kokoro", "kokoro_lang": "te",
           "voices": {"female": "hf_alpha", "male": "hm_omega"}, "font": "Noto Sans Telugu"},
}

# Force one engine everywhere (e.g. BLU_TTS=silent while models are not installed)
TTS_OVERRIDE = os.environ.get("BLU_TTS")

# the int8 model is ~3x smaller and faster on CPU; used automatically if present
KOKORO_ONNX = MODELS_DIR / ("kokoro-v1.0.int8.onnx" if (MODELS_DIR / "kokoro-v1.0.int8.onnx").exists() else "kokoro-v1.0.onnx")
KOKORO_VOICES = MODELS_DIR / "voices-v1.0.bin"
PARLER_MODEL = os.environ.get("PARLER_MODEL", "ai4bharat/indic-parler-tts")

SAMPLE_RATE = 24000
PAUSE_BETWEEN_BEATS = 0.25  # seconds
PAUSE_AFTER_SCENE = 0.6

# ---- Export ----
EXPORT_FPS = int(os.environ.get("BLU_FPS", "15"))  # diagrams look smooth at 15 fps; fewer frames = faster MP4
SERVER_URL = os.environ.get("BLU_SERVER", "http://127.0.0.1:8000")
