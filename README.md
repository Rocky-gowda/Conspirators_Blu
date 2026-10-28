# Blu Visual Teacher

**Type any topic → get a short animated video lesson, spoken in English or an Indian language, in seconds.
Upload your notes → get a practice test. Everything works with Wi-Fi OFF, on an ordinary laptop.**

---

## Part A: Blu in simple words (for everyone)

### What is Blu?

Imagine a teacher who lives inside your laptop. You type *"How do plants make food?"* and the teacher:

1. **understands** what you mean, even with spelling mistakes ("phito systhse" → *Did you mean photosynthesis?*),
2. **decides which pictures** will explain it best (a plant with arrows for sunlight, water and air going in),
3. **writes** a short lesson for your level (beginner, intermediate or advanced),
4. **speaks** it in English, Hindi, Kannada, Marathi, Bengali, Tamil or Telugu, with captions in that script,
5. **draws and animates** each part while it is being spoken,
6. **saves** it as a video (MP4) you can keep or share.

And it never needs the internet, because every "brain" it uses is stored on the laptop.

### The two modes

| Mode | You give | You get |
|---|---|---|
| 🎓 **Learn** | a topic | a 30–90 second animated, narrated lesson + MP4 video |
| 📝 **Exam** | your PDF notes | a practice test made from *your* notes, a score, your weak topics, and a "Learn this" button |

### The helpers inside Blu

A **model** is a computer brain that learned one skill by studying lots of examples. Blu has a small team:

| Helper | Its job, in simple words |
|---|---|
| **Qwen2.5 1.5B** (fast writer) | writes the lesson's sentences for new topics, quickly |
| **Phi-4-mini** (careful writer) | a bigger writer, used in "quality mode" and as a backup |
| **nomic-embed-text** (librarian) | finds the right page in Blu's notebook *by meaning*, even if you use different words |
| **IndicTrans2** (translator) | turns English into Indian languages |
| **Kokoro** (voice) | reads the lesson aloud with an Indian accent, male or female |
| **SymSpell** (spell-checker) | fixes typing mistakes but never changes names |

Plus tools that are not AI: **FFmpeg** (makes the video file), **Chromium** (draws each video frame),
**pypdf** (reads PDFs), **FastAPI** (the "waiter" that carries your request to the helpers).

### ⭐ What makes Blu special (our extra features)

| Feature | What it means for you |
|---|---|
| ⚡ **Starts almost instantly** | the video starts playing in about a second; the rest is prepared *while you watch* |
| 🧠 **Visual reasoning** | before writing, Blu decides the best picture for each part (picture, steps, cycle, table, shape, timeline…) and shows *why* in a "Visual reasoning" box |
| 🖼️ **Pictures for any topic** | 49 built-in drawings (plant, sun, heart, battery, atom…) plus emoji pictures for everything else; arrows show what goes in and what comes out |
| 📐 **Real shapes** | "circle" draws an exact circle; radius, diameter and circumference appear as the voice names them (also triangles, squares, polygons, angles) |
| 📊 **Tables** | "difference between acids and bases" becomes a table whose rows appear one by one |
| 🎚️ **Three real levels** | beginner, intermediate and advanced get *different* scenes, examples, code and quizzes, not just a different speed |
| ✏️ **Understands messy typing** | fixes spelling, missing spaces and swapped letters; asks "Did you mean…?" when unsure; never "corrects" names like *Sachin Tendulkar* |
| 🎯 **Stays on topic** | if the AI writes about the wrong subject, Blu rejects it and asks once more, telling it what was wrong; it never plays a lesson about a different topic |
| ✅ **Checked lessons** | 12 topics are written and checked by the team; they play instantly and are marked "Built on checked notes"; everything else is marked "AI knowledge, not verified" |
| 🚫 **No made-up numbers** | for topics without checked notes, sentences with big unverified numbers (like "100,000 runs") are left out |
| 📏 **Right length** | if you choose 60 seconds, the *whole* video is about 60 seconds, with at least 3 real scenes |
| 📱 **Works on a phone** | open the laptop's address on a phone on the same hotspot; the video plays smoothly |
| 📝 **Exam mode with proof** | every question shows the sentence from *your* PDF that proves the answer; made-up questions are thrown away |
| 🗂️ **History** | replay, re-voice in another language, edit a scene, download, or delete old lessons |
| 🌗 **Light and dark mode** | one click |
| 🔌 **Wi-Fi off** | tested with the network blocked: no connection to the internet is ever attempted |

### Words you may hear (mini glossary)

| Word | Meaning |
|---|---|
| **Offline** | works without the internet |
| **LLM** | "Large Language Model": an AI that reads and writes sentences |
| **Ollama** | the program that keeps AI models on the laptop and runs them |
| **JSON / schema** | a strict "worksheet" the AI must fill in; the schema is the rule sheet for it |
| **Embedding / semantic search** | turning sentences into numbers so that sentences with the same *meaning* are close together |
| **TTS** | Text-To-Speech: text in, voice out |
| **Latency** | waiting time |
| **Fallback** | a safe backup plan when something fails |
| **MP4, H.264, AAC** | the video file and the "languages" its picture and sound are stored in, so any phone can play it |
| **Licence** | the permission note that says how you may use something |

---

## Part B: Setup and running (Windows)

### B1. One-time setup (needs internet)

1. Install the tools (Command Prompt):
   ```
   winget install Python.Python.3.11
   winget install Ollama.Ollama
   winget install Gyan.FFmpeg
   ```
   Close Command Prompt and open a new one.
2. Download the AI models:
   ```
   ollama pull qwen2.5:1.5b
   ollama pull phi4-mini
   ollama pull nomic-embed-text
   ```
3. In the `blu` folder, run `install.bat` (installs the Python packages and the video browser).
4. Translation model (IndicTrans2) is "gated": make a free Hugging Face account, open
   <https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M>, accept the terms, create a "Read" token, then:
   ```
   py -3.11 -m pip install huggingface_hub
   py -3.11 -c "from huggingface_hub import login; login()"
   py -3.11 -c "from huggingface_hub import snapshot_download; snapshot_download('ai4bharat/indictrans2-en-indic-dist-200M')"
   ```
5. Voice model (Kokoro): create a `models` folder inside `blu` and download:
   ```
   curl -L -C - --retry 5 -o models\kokoro-v1.0.int8.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx
   curl -L -C - --retry 5 -o models\voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
   ```
   Moving to a new Blu folder? Copy the old `models` folder (and `data`, to keep your history).

### B2. Run it

```
run.bat
```

Open <http://127.0.0.1:8000> in Chrome. Wait until the pill at the top says **Offline ready** (models
load into memory once). Keep the black window open: closing it stops the app.

- **In VS Code:** File → Open Folder → `blu`, open the terminal (Ctrl + \`), choose Command Prompt, type `run.bat`.
- **Phone:** connect phone and laptop to the same hotspot, find the laptop's IPv4 address with `ipconfig`,
  open `http://<that-address>:8000` on the phone. (One time, in an administrator Command Prompt:
  `netsh advfirewall firewall add rule name="Blu Visual Teacher" dir=in action=allow protocol=TCP localport=8000`.)
- **Wi-Fi-off check:** turn Wi-Fi off, run `run.bat`, make a lesson in English and Hindi, download the MP4.
- **Optional:** `prebake.bat` (with the app running) prepares the checked lessons in advance.
- **Updates:** an `update_blu.py` file is applied with `py -3.11 update_blu.py` inside the `blu` folder;
  it backs up the old files first.

### B3. Using the app

**Learn:** type a topic → under the box Blu shows what it understood (subject, person/place/concept, fixed
spellings, how it searched) → choose level, length, language, voice → **Create lesson**. The stage list shows
each step's time, **Ready to play** and **First teaching slide**; the **Visual reasoning** box shows the
picture chosen for each scene and why; **Speed & memory** shows the peak memory. Under the player:
**Download MP4** (recorded in the background), **Captions (.srt)**, **Revoice** (another language, voice or
speed, no AI needed), **Edit a scene**.

**Exam:** upload a text PDF (try `samples/Science_notes_plants_and_water.pdf`) → choose the number of
questions, difficulty, question types, timer → take the test (question palette, mark for review, keyboard
1–4 / N / P) → results: score, score per topic, weak areas, explanations, the proving line from your PDF,
**Retake**, **Learn this**.

**History:** every lesson and exam, with play, download and delete (with confirmation) and **Clear all**.

---

## Part C: How it works (technical)

### C1. The pipeline

```
 what the learner typed
   │ understand (offline, < 5 ms): normalise → key words → spelling (SymSpell + subject words, names
   │ protected, unsure → "did you mean?") → people / places / organisations → intent → broad/random check
   ▼
 search the checked notes: meaning (nomic-embed-text, kept loaded) + keywords (BM25); relevance check;
   up to 3 reworded tries in ONE embedding call ─► checked topic / related background / nothing
   ▼
 checked topic (strong match)?  ──yes──► the checked lesson for this level and length, instantly
   │ no
   ▼
 VISUAL REASONING (rules, < 1 ms): the picture for each scene, from what the topic IS
   (process → picture with arrows, cycle, parts, steps, timeline, numbers → worked example, amounts → chart,
    comparison → table, shape → exact geometry, code → code walkthrough) + level order + length
   ▼
 instant start: title card with the topic's own drawings is voiced and PLAYS (no AI needed yet)
   ▼
 local AI (Ollama, fast model) writes only headings, labels and sentences in a compact JSON format, following
   the visual plan; each scene is streamed, checked, translated and voiced while the previous one plays
   ▼
 checks on every scene: on topic? English? repeated? labels not copied? sentences complete? no unverified
   big numbers? quiz answer taught?  →  bad scene: ask for that one scene again (max 2)  →  answer unusable:
   ONE retry with the reasons  →  else checked notes (strong match only)  →  else an honest message
   ▼
 voice-first timeline (the voice sets each scene's length) → player → MP4 recorded in the background
   (Playwright frames + FFmpeg, H.264 Main / AAC, 720p, fast start, verified with ffprobe)
```

```
 PDF ─► text, headings, chunks (pypdf) ─► questions from the AI, each with an evidence quote
     ─► the quote must really be in the PDF (else the question is dropped) ─► offline question maker fills gaps
     ─► test ─► graded on the server (answers are never sent to the browser before submitting)
```

### C2. Problem statement coverage

| Requirement | How Blu meets it |
|---|---|
| Topic → 30–90 s narrated animated lesson | lengths 30 / 45 / 60 / 75 / 90 s; the length is the whole video, checked after building |
| English (Indian accent) + 2 Indian languages | 7 languages; Kokoro Indian English and Hindi voices, female and male |
| Captions in the correct script | IndicTrans2; Noto fonts for Devanagari, Kannada, Bengali, Tamil, Telugu |
| Play / pause / next / replay in the browser | `frontend/player.*` (keyboard too: space, arrows, R) |
| 720p H.264/AAC MP4 | `backend/exporter.py`; each MP4 is checked with ffprobe (codec, size, length) |
| Local LLM, JSON only, schema validation, fallback | Ollama `format` = JSON schema; Pydantic; repair in code; checked fallback lessons |
| Title card, labelled diagram with arrows, code walkthrough | plus picture (illustration), shape, table, timeline, chart, worked example, quiz, recap |
| Voice sets the scene length | `backend/timeline.py` |
| Licences in the README | section D2 |

### C3. Understanding the topic (NLP and semantic search)

| Step | Example |
|---|---|
| Spelling: only non-words change; subject words first; English words only when clearly right | `pyton` → python, `binary serch algoritm` → binary search algorithm, `pyhsics of blak holes` → physics of black holes |
| Missing / extra spaces | `photo synthesis` → photosynthesis, `binarysearch` → binary search |
| Not sure → ask | `phito systhse` → "Did you mean photosynthesis?" |
| Names protected | `sachin tendulkar`, `rahul dravid`, `Virat Kohli` stay as typed; "General AI" is a concept, not a person |
| Entities and intent | Virat Kohli → person; Taj Mahal → place; ISRO → organisation; "how…" → explain how/why |
| Broad or random | "Artificial Intelligence" → narrower choices; "asdf qwer" → politely refused |
| Meaning search | "how green plants make food using sunlight" → photosynthesis |
| No false matches | "how does a car engine work" is **not** Newton's laws (only related background); "python works" → Python basics |

A topic outside the checked notes is still taught by the AI (labelled "not verified"); there is no fixed list
of allowed topics.

### C4. Visual reasoning, levels, scenes and length

| The topic is… | Picture chosen | Example |
|---|---|---|
| a process (things in, things out) | picture: main thing in the centre, arrows in and out | photosynthesis; how AI learns (emoji 💻📊 → 🤖 → 🎯) |
| "how does it work" / "what is" | picture first for beginners, then steps or key points | vaccines, the internet, gravity |
| a cycle | cycle diagram | water cycle |
| a thing with parts | labelled hub | heart, solar system |
| a comparison | table, rows appear with the voice | acids vs bases |
| a shape | exact animated geometry | circle, triangle, Pythagoras (right triangle) |
| a person / place / organisation | timeline + "known for" | Virat Kohli, Taj Mahal, ISRO |
| a rule with numbers / maths | worked example | Ohm's law, circle area |
| amounts | bar chart | where Earth's water is |
| programming | code walkthrough + trace (advanced: a harder second example) | Python |

**Levels:** beginner = everyday words, picture first; intermediate = how and why, a common mistake, no repeat
of basics; advanced = the mechanism, numbers, edge cases. Example (Python basics): first program → functions
and lists (why `/` gives `80.0`) → what CPython does and generators.

**Length:** the chosen length is the whole video. Checks stored in `meta.json → checks`: total length within
±15 % (or ±6 s for short lessons), at least 3 scenes after the title, no scene under 2 s. Measured on all 165
checked lessons (12 topics × 3 levels × 5 lengths at the time: 11 topics): 164 pass; median within ±6 %.

**On screen:** every label is measured and shrunk until it fits its box; long captions get a smaller font;
idle animations (floating drawings, flowing particles, pulsing parts) keep the screen alive.

### C5. Speed

| Step | Time (test machine) |
|---|---|
| Understanding + visual plan | under 5 ms |
| Checked topic: lesson ready, first teaching slide | about 0.2–0.3 s to play, done in about 1 s |
| New topic: title playing | about 0.1–0.5 s, before the AI writes anything |
| New topic: first teaching slide | when the AI finishes its (short) first scene; shown in the stage list |
| MP4 file | 19–22 s for a 60 s lesson, **in the background** (was 23–40 s, blocking) |

How: checked lessons need no AI; the title card needs no AI; a small fast model; the AI writes 42–53 % less
text (compact format, structure decided by the visual plan); its instructions are pre-loaded at start-up and
only about 215 tokens per topic; the search model stays loaded; slides are checked for every 0.3 s; the MP4
is recorded in the background and reuses still frames. Fastest option: `ollama pull qwen2.5:0.5b` and
`set BLU_FAST_MODEL=qwen2.5:0.5b` before `run.bat` (faster, simpler lessons).

---

## Part D: For the judges

### D1. Everything Blu needs

| Component | Name / version | Purpose | Size | Licence | Offline? |
|---|---|---|---|---|---|
| Python | 3.11 | runs the app | ~100 MB | PSF | yes |
| Python packages | `requirements.txt` (FastAPI, uvicorn, pydantic, transformers 4.46.1, torch, kokoro-onnx, pypdf, psutil, symspellpy 6.10.1…) | server, translation, voice, PDF, memory, spelling | ~2.5 GB with torch | see D2 | yes |
| Ollama | 0.x | runs the AI models | ~1 GB | MIT | yes |
| Fast LLM (default) | `qwen2.5:1.5b` | writes lessons for new topics | ~1 GB | Apache-2.0 | yes |
| Quality LLM / backup | `phi4-mini` | `BLU_SPEED=quality`, exam questions | 2.5 GB | MIT | yes |
| Embeddings | `nomic-embed-text` | meaning search | 274 MB | Apache-2.0 | recommended |
| Translation | `ai4bharat/indictrans2-en-indic-dist-200M` | English → Indian languages | ~2.2 GB | MIT | yes |
| Voice | `kokoro-v1.0.int8.onnx` + `voices-v1.0.bin` | narration | 88 MB + 27 MB | Apache-2.0 | yes |
| Spelling dictionary | inside symspellpy | spelling | 1.3 MB | MIT | yes |
| Fonts | Noto Sans family | captions in every script | 6.5 MB | OFL 1.1 | yes |
| Video | FFmpeg (x264), Chromium (Playwright) | MP4 | ~300 MB | GPL / BSD | yes |

Not used on purpose: spaCy, sentence-transformers, FAISS (not needed for our small notebook), image
generators (too slow on a CPU; built-in drawings and emoji are clearer for teaching).

### D2. Licences

| Component | Version | Purpose | License | Source | Restrictions |
|---|---|---|---|---|---|
| Qwen2.5 1.5B Instruct (weights) | qwen2.5:1.5b | fast lesson writing | Apache-2.0 | https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct | keep notice; state changes |
| Phi-4-mini (weights) | phi4-mini (3.8B, Q4) | quality mode, exam questions | MIT | https://huggingface.co/microsoft/Phi-4-mini-instruct | keep notice |
| nomic-embed-text (weights) | latest Ollama tag | meaning search | Apache-2.0 | https://ollama.com/library/nomic-embed-text | keep notice |
| Ollama (runtime) | 0.x | runs the models | MIT | https://github.com/ollama/ollama | keep notice |
| IndicTrans2 en→indic dist-200M | dist-200M | translation | MIT | https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M | gated: accept terms |
| Kokoro-82M (weights) | v1.0 int8 ONNX | narration | Apache-2.0 | https://huggingface.co/hexgrad/Kokoro-82M | keep notice |
| Kokoro voices (hf_alpha, hf_beta, hm_omega, hm_psi) | voices-v1.0.bin | Indian voices | Apache-2.0 | https://github.com/thewh1teagle/kokoro-onnx/releases | keep notice |
| kokoro-onnx | 0.6.1 | runs Kokoro | MIT | https://github.com/thewh1teagle/kokoro-onnx | keep notice |
| espeak-ng (espeakng-loader) | 0.2.4 | pronunciation | GPL-3.0 | https://github.com/espeak-ng/espeak-ng | unmodified separate library; provide source if redistributed |
| symspellpy + frequency dictionary | 6.10.1 | spelling | MIT | https://github.com/mammothb/symspellpy | keep notice |
| onnxruntime | 1.x | voice model runtime | MIT | https://github.com/microsoft/onnxruntime | keep notice |
| Transformers | 4.46.1 | IndicTrans2 | Apache-2.0 | https://github.com/huggingface/transformers | keep notice |
| PyTorch | 2.x | IndicTrans2 | BSD-3-Clause | https://pytorch.org | keep notice |
| sentencepiece | 0.2.x | IndicTrans2 tokens | Apache-2.0 | https://github.com/google/sentencepiece | keep notice |
| indic-nlp-library | 0.92 | script conversion | MIT | https://github.com/anoopkunchukuttan/indic_nlp_library | keep notice |
| FastAPI / Uvicorn / Pydantic | 0.1xx / 0.x / 2.x | web server, validation | MIT / BSD-3 / MIT | github.com/fastapi, encode/uvicorn, pydantic | keep notice |
| requests / NumPy / soundfile | 2.x / 2.x / 0.1x | HTTP, audio | Apache-2.0 / BSD-3 / BSD-3 | psf/requests, numpy.org, bastibe/python-soundfile | keep notice |
| pypdf / psutil | 6.x / 7.x | PDF text, memory | BSD-3 / BSD-3 | py-pdf/pypdf, giampaolo/psutil | keep notice |
| Playwright + Chromium | 1.x | video frames | Apache-2.0 / BSD-3 | microsoft/playwright-python, chromium.org | keep notices |
| FFmpeg (Gyan build, x264) | 7.x | MP4 encoding | GPL-3.0 build | https://ffmpeg.org | installed separately, not shipped |
| Noto Sans fonts | 2.x | captions | SIL OFL 1.1 | https://fonts.google.com/noto | not sold alone; `frontend/fonts/OFL.txt` |
| Emoji | system font (Segoe UI Emoji) | pictures and icons | system font | Windows | not shipped |
| 49 built-in drawings, 12 checked lessons, sample PDF, app code | — | this project | written by the team during the event | this repo | — |

### D3. Tests and results

```
py -3.11 -m unittest tests.test_core tests.test_understanding   # 85 unit tests
py -3.11 tests/run_all_tests.py                                  # 25 integration + system tests
```

The system tests start a **fake** local AI and a test copy of the app with **the network blocked**
(`tests/offline_guard`), so they test Blu's logic and offline behaviour, not the real model's writing quality.

**Unit tests: 85 / 85 passed (also on Python 3.11).** They cover spelling (every example in the brief),
names, spaces, "did you mean", search and false matches, person vs topic, prompts, levels, length and scene
count, visual reasoning, pictures, emoji, shapes, tables, compact format, lazy AI answers, copied labels,
cut-off and repeated sentences, unverified numbers, text fitting, exam grading and path safety.

**System tests (last clean run): 24 passed, 1 skipped, 0 failed.**

| Scenario | Result |
|---|---|
| Valid topic → narrated lesson + verified MP4 (H.264 Main 1280×720) | PASS |
| "phito systhse" → "Did you mean photosynthesis?" → lesson | PASS |
| Virat Kohli → person lesson, labelled not verified | PASS |
| Broad topic → narrower choices; random text → refused | PASS |
| Python at 3 levels → 3 different lessons | PASS |
| Photosynthesis → picture with sun, water, CO₂ in; glucose, O₂ out | PASS |
| Comparison topic → table | PASS |
| 30 s and 60 s → right length, 3+ scenes, MP4 checked | PASS |
| Off-topic AI answer → one retry with reasons → accepted; still wrong → honest message | PASS |
| AI leaves out labels → lesson still complete | PASS |
| AI stops half-way → finished from checked notes | PASS |
| Slow AI → playing after 0.1 s; checked topic done after 1.2 s; MP4 in the background | PASS |
| Exported MP4 plays in a browser (0 dropped frames, fast start) | PASS |
| Exam from a PDF (made-up question dropped); broken PDF refused | PASS |
| History delete (path tricks refused); revoice without AI | PASS |
| Ollama off → checked lesson or clear message; voice files missing → clear error | PASS |
| Network blocked for the whole run → no outside connection attempted | PASS |
| Hindi translation + narration | **SKIPPED** on the test machine (model not installed there): **checked on the laptop** |

### D4. Tested on (laptop)

| Laptop | CPU | RAM | Model | First teaching slide (new topic) | Lesson done | MP4 | Peak memory |
|---|---|---|---|---|---|---|---|
| _fill in_ | | 16 GB | qwen2.5:1.5b | | | | |

(The numbers are in the stage list and the Speed & memory box after each lesson.)

### D5. Known limitations

- Exam mode needs a text PDF (no OCR for scanned pages).
- Topics outside the 12 checked lessons use the AI's general knowledge (labelled "not verified"); a small
  model can still make mistakes, which is why big unverified numbers are removed.
- Kannada, Bengali, Tamil and Telugu use the Hindi Kokoro voices with each language's pronunciation rules.
- On a CPU-only laptop the full AI-written lesson takes longer than its first slide; playback starts first.
- Emoji pictures depend on the system emoji font (built in on Windows).

### D6. Settings

| Variable | Default | Use |
|---|---|---|
| `BLU_SPEED` | `fast` | `fast` = small model when installed; `quality` = `OLLAMA_MODEL` |
| `BLU_FAST_MODEL` | `qwen2.5:1.5b` | e.g. `qwen2.5:0.5b` for the fastest lessons |
| `OLLAMA_MODEL` | `phi4-mini` | quality mode and backup |
| `BLU_COMPACT` | `1` | compact AI format (`0` = full scene objects) |
| `BLU_KB_FIRST` | `1` | checked topics play the checked lesson at once (`0` = always ask the AI) |
| `BLU_FPS` / `BLU_BEAMS` | `15` / `2` | MP4 frame rate / translation quality |
| `BLU_TTS` | per language | `silent` for testing only |

### D7. Project structure

```
backend/   app.py (API) · pipeline.py (stages, streaming, checks, background MP4) · topic_nlp.py + spelling.py
           (understanding) · retrieval.py (search) · visual_plan.py (visual reasoning, icons) · planner.py
           (prompt, compact format, repair) · schema.py (scene types) · knowledge/ (12 checked lessons)
           translate.py · tts.py · timeline.py · exporter.py · documents.py + exam.py · memory.py · warmup.py
frontend/  index.html, app.js, app.css (app) · player.html, player.js, player.css (player, scenes, 49 drawings)
tests/     test_core.py, test_understanding.py (unit) · run_all_tests.py (system) · fake_ollama.py · offline_guard/
samples/   sample PDF · install.bat · run.bat · prebake.bat · requirements.txt
```

### D8. Troubleshooting

| You see | Fix |
|---|---|
| browser: `ERR_CONNECTION_REFUSED` / "Starting…" forever | the app is not running: start `run.bat` and keep its window open |
| "only one usage of each socket address" | already running: `taskkill /F /IM python.exe`, then `run.bat` |
| "Ollama is not running" | open the Ollama app |
| new topics slow | choose 45 s, or use `qwen2.5:0.5b` (section C5) |
| pill "Offline · 4/5 ready" | hover it; usually `ollama pull nomic-embed-text` |
| "Voice model missing" | `models\kokoro-v1.0.int8.onnx` and `models\voices-v1.0.bin` must exist |
| `No module named …` | run `install.bat` again |
| buttons do nothing after an update | press Ctrl + F5 (or clear the browser cache) |
| PDF refused | it is scanned or almost empty: use a text PDF |
