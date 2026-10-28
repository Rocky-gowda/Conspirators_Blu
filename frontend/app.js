// Blu Visual Teacher — app shell logic (no frameworks, works offline).
"use strict";
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
async function api(url, opt = {}) {
  const r = await fetch(url, opt);
  let j = null; try { j = await r.json(); } catch (e) {}
  if (!r.ok) { const d = j && j.detail; const err = new Error(typeof d === "string" ? d : (d && d.message) || `Request failed (${r.status})`); err.status = r.status; err.detail = d; throw err; }
  return j;
}
function toast(msg) { const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; document.body.appendChild(t); setTimeout(() => t.remove(), 2600); }
function confirmBox(title, text, yes = "Delete") {
  return new Promise(res => {
    $("mTitle").textContent = title; $("mText").textContent = text; $("mYes").textContent = yes; $("modal").hidden = false; $("mYes").focus();
    const done = v => { $("modal").hidden = true; $("mYes").onclick = $("mNo").onclick = null; res(v); };
    $("mYes").onclick = () => done(true); $("mNo").onclick = () => done(false);
    $("modal").onclick = e => { if (e.target === $("modal")) done(false); };
  });
}
const ago = iso => { if (!iso) return ""; const s = (Date.now() - new Date(iso)) / 1000; return s < 60 ? "just now" : s < 3600 ? Math.round(s / 60) + " min ago" : s < 86400 ? Math.round(s / 3600) + " h ago" : new Date(iso).toLocaleDateString(); };
const fmtTime = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// ---------------------------------------------------------------- theme
function setThemeIcon() {
  const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  $("themeIcon").setAttribute("d", dark ? "M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z"
    : "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z");
}
$("theme").onclick = () => {
  const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "light" : "dark"; store.set("blu-theme", document.documentElement.dataset.theme); setThemeIcon();
};
setThemeIcon();

// ---------------------------------------------------------------- routing
const PAGES = ["home", "learn", "exam", "test", "results", "history"];
function route() {
  let p = (location.hash || "#home").slice(1).split("?")[0];
  if (!PAGES.includes(p)) p = "home";
  if ((p === "test" || p === "results") && !exam.id) p = "exam";
  PAGES.forEach(x => $("p-" + x).hidden = x !== p);
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.toggle("on", a.dataset.nav === p || (a.dataset.nav === "exam" && (p === "test" || p === "results"))));
  if (p === "history") loadHistory();
  if (p === "learn") loadRecent();
  if (p === "exam") loadPastExams();
  window.scrollTo(0, 0);
}
addEventListener("hashchange", route);

// ---------------------------------------------------------------- status + features
function warm() {
  api("/api/warmup").then(s => {
    const v = Object.values(s), ready = v.filter(x => x.startsWith("ready")).length, loading = v.some(x => x === "loading") || v.length < 5;
    const el = $("status"), all = !loading && ready === v.length;
    el.className = "pill " + (loading ? "" : all ? "ok" : "warn");
    el.querySelector(".txt").textContent = loading ? "Loading models…" : all ? "Offline ready" : `Offline · ${ready}/${v.length} ready`;
    el.title = Object.entries(s).map(([k, x]) => `${k}: ${x}`).join("\n");
    if (loading) setTimeout(warm, 2000);
  }).catch(() => setTimeout(warm, 3000));
}
const ICON = {
  pdf: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  nlp: '<path d="M4 6h16M4 12h10M4 18h7"/><circle cx="18" cy="16" r="3"/><path d="m21 19 1.5 1.5"/>',
  ai: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 10h4v4h-4z"/>',
  vis: '<rect x="3" y="4" width="7" height="6" rx="1.5"/><rect x="14" y="14" width="7" height="6" rx="1.5"/><path d="M10 7h4a3 3 0 0 1 3 3v4"/>',
  voice: '<path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  mp4: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/>',
  quiz: '<path d="M9 11l2 2 4-4"/><rect x="4" y="3" width="16" height="18" rx="2"/>',
  prog: '<path d="M4 19V9M10 19V5M16 19v-7M22 19H2"/>',
  off: '<path d="M2 8.8a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19.5" r="1"/>',
};
const FEATURES = [["pdf", "Upload PDF notes"], ["nlp", "NLP topic understanding"], ["ai", "AI-powered lessons"], ["vis", "Visual reasoning"],
  ["voice", "Multilingual narration"], ["mp4", "Synchronized MP4 export"], ["quiz", "Practice questions"], ["prog", "Track progress"], ["off", "Offline learning"]];
$("features").innerHTML = FEATURES.map(([i, t]) => `<div class="feat"><span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON[i]}</svg></span><div><b>${t}</b><small>✓ Available</small></div></div>`).join("");

// ---------------------------------------------------------------- languages
let LANGS = [];
api("/api/languages").then(ls => {
  LANGS = ls;
  const opts = ls.map(l => `<option value="${l.code}">${esc(l.name)} (${l.code})</option>`).join("");
  for (const id of ["language", "relang", "exLang"]) $(id).innerHTML = opts;
});

// ================================================================ LEARN
const STAGES = [["understand", "Understanding topic"], ["plan", "Writing the lesson (local AI)"], ["translate", "Translating"],
  ["voice", "Narration + sync"], ["ready_to_play", "Ready to play"], ["first_teaching_slide", "First teaching slide"], ["export_mp4", "Rendering MP4"]];
const EXAMPLES = ["How do plants make food?", "How does a Python loop work?", "Explain Ohm's law", "How does the heart pump blood?", "Pythagorean theorem", "Virat Kohli"];
const DOMAIN = { programming: "💻 Programming", biology: "🧬 Biology", physics: "⚛️ Physics", chemistry: "⚗️ Chemistry", math: "➗ Maths",
  earth: "🌍 Earth science", history: "🏛️ History", person: "👤 Person", general: "💡 General" };
let lessonId = null, timeline = null, level = "beginner", lastAnalysis = null, busy = false;

$("examples").innerHTML = EXAMPLES.map(e => `<button type="button">${esc(e)}</button>`).join("");
$("examples").onclick = e => { if (e.target.tagName === "BUTTON") { $("topic").value = e.target.textContent; understand(); } };
$("level").onclick = e => { const b = e.target.closest("button"); if (!b) return; level = b.dataset.v; [...$("level").children].forEach(x => x.classList.toggle("on", x === b)); };
$("speed").oninput = () => $("speedv").textContent = (+$("speed").value).toFixed(2) + "×";

function highlight(text, words) {
  let h = esc(text);
  for (const w of words || []) if (w.length > 2) h = h.replace(new RegExp(`\\b(${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})\\b`, "ig"), '<mark class="hl">$1</mark>');
  return h;
}
let ut = null;
function understand() {
  clearTimeout(ut);
  ut = setTimeout(async () => {
    const t = $("topic").value.trim();
    $("choice").hidden = true;
    if (t.length < 3) { $("understood").innerHTML = ""; return; }
    let a; try { a = await api("/api/analyze?topic=" + encodeURIComponent(t)); } catch (e) { return; }
    lastAnalysis = a;
    let h = "";
    if (a.fixes.length) h += `<span class="chip warn">✎ ${a.fixes.map(f => esc(f[0]) + " → " + esc(f[1])).join(", ")}</span>`;
    h += `<span class="chip blu">${DOMAIN[a.domain] || esc(a.domain)}</span>`;
    for (const e of a.entities) h += `<span class="chip">${e.type === "person" ? "👤" : e.type === "place" ? "📍" : "🏢"} ${esc(e.text)}</span>`;
    if (a.status === "ok") h += a.kb ? `<span class="chip ok">✓ Checked notes · ${a.facts.length} facts</span>` : `<span class="chip">AI knowledge (not verified)</span>`;
    if (a.retrieval && a.retrieval.method) h += `<span class="chip" title="How Blu searched its offline notes">🔎 ${esc(a.retrieval.method)}${a.retrieval.attempts && a.retrieval.attempts.length > 1 ? ` · ${a.retrieval.attempts.length} tries` : ""}</span>`;
    $("understood").innerHTML = h;
    if (a.status !== "ok") showChoice(a);
  }, 380);
}
$("topic").addEventListener("input", understand);
function showChoice(a, viaSubmit) {
  const box = $("choice");
  box.className = "choice" + (a.status === "invalid" ? " bad" : "");
  const kw = a.highlights && a.highlights.length ? `<div style="margin-top:6px">Key words found: ${highlight(a.highlights.join(", "), a.highlights)}</div>` : "";
  box.innerHTML = `<b>${a.status === "broad" ? "This topic is very big" : a.status === "unclear" ? "Did you mean…?" : "I couldn't understand that"}</b>
    <div style="margin-top:4px">${esc(a.message)}</div>${a.status === "unclear" ? kw : ""}
    <div class="opts">${(a.suggestions || []).map(s => `<button type="button" data-s="${esc(s)}">${esc(s)}</button>`).join("")}
    ${a.status !== "invalid" ? `<button type="button" data-asis="1">Continue as typed</button>` : ""}</div>
    ${a.status === "unclear" ? '<div style="margin-top:8px;font-size:13px;color:var(--muted)">This is a suggestion, not a guess at what you meant.</div>' : ""}`;
  box.hidden = false;
  box.onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.s) { $("topic").value = b.dataset.s; understand(); generate(false); }
    if (b.dataset.asis) generate(true);
  };
}

function showStages(job) {
  $("stages").innerHTML = STAGES.map(([k, name]) => {
    const t = job.timings[k], on = job.stage === k && t === undefined && !["error", "done"].includes(job.status);
    const pct = on && job.progress && k !== "understand" ? ` ${Math.round(job.progress * 100)}%` : "";
    const st = t !== undefined ? "ok" : on ? "on" : "";
    const bg = k === "export_mp4" && t === undefined && job.mp4_state === "rendering";
    return `<li class="${st || (bg ? "on" : "")} ${k === "ready_to_play" ? "big" : ""}"><span class="st">${t !== undefined ? "✓" : ""}</span><span>${name}${bg ? " (in the background, watch now)" : ""}</span><span class="t">${t !== undefined ? t.toFixed(1) + " s" : on || bg ? "…" + pct : ""}</span></li>`;
  }).join("") + (job.mp4 ? `<li class="ok"><span class="st">✓</span><span>MP4 checked (720p · H.264 · AAC)</span></li>` : "");
  $("detail").textContent = job.status === "done" ? "" : (job.detail || "");
  $("notesBox").hidden = !job.notes.length;
  $("notes").textContent = job.notes.join("\n");
  // visual reasoning: which picture was chosen for each part of the lesson, and why
  const vp = job.visual;
  let vb = $("visualbox");
  if (!vb) { vb = document.createElement("div"); vb.id = "visualbox"; vb.className = "speed"; $("speedbox").before(vb); }
  vb.hidden = !(vp && vp.scenes && vp.scenes.length);
  if (!vb.hidden) {
    const ICONV = { illustration: "🖼️", diagram: "🔀", code_walkthrough: "💻", timeline: "🕒", chart: "📊", worked_example: "🧮" };
    vb.innerHTML = `<b>Visual reasoning</b> <span style="opacity:.7">· ${esc(vp.summary)}</span>` +
      vp.scenes.map((s, i) => `<div style="margin-top:6px">${ICONV[s.type] || "▪️"} <b>Scene ${i + 2}: ${esc(s.type.replace("_", " "))}${s.layout ? " (" + esc(s.layout) + ")" : ""}</b><br><span style="opacity:.8">${esc(s.why)}</span>${s.art ? `<br><span style="opacity:.7">drawings: ${s.art.map(esc).join(", ")}</span>` : ""}</div>`).join("") +
      (vp.planned ? `<div style="margin-top:6px">✓ followed in ${vp.followed} of ${vp.planned} scenes</div>` : "") +
      (vp.note ? `<div style="margin-top:6px;opacity:.8">${esc(vp.note)}</div>` : "");
  }
  const m = job.memory || {};
  if (m.peak_mb) {
    const gb = x => (x / 1024).toFixed(1);
    $("speedbox").hidden = false;
    $("speedbox").innerHTML = `<b>Speed &amp; memory</b><br>Peak memory <b>${gb(m.peak_mb)} GB</b> of ${gb(m.system_mb)} GB (AI model ${gb(m.ollama_mb)} GB · app ${gb(m.app_mb)} GB)` +
      (job.timings.ready_to_play ? `<br>Ready to play in <b>${job.timings.ready_to_play.toFixed(1)} s</b>` : "");
  }
}
function setBusy(b) { busy = b; $("go").disabled = b; $("revoice").disabled = b; $("saveScene").disabled = b; $("go").textContent = b ? "Working…" : "Create lesson"; }
let pollToken = 0;
async function pollJob(job) {
  const me = ++pollToken;                               // a newer lesson stops this loop
  let shown = null, finished = false;
  while (me === pollToken) {
    showStages(job);
    if (job.lesson_id && shown !== job.lesson_id) { shown = job.lesson_id; showPlayer(job.lesson_id, true); }
    if (job.mp4) { $("mp4btn").disabled = false; $("mp4btn").textContent = "⬇ Download MP4"; }
    if (job.status === "error") { $("err").textContent = job.error; setBusy(false); return; }
    if (job.status === "done" && !finished) {
      finished = true;                                  // the lesson is ready: the learner can go on now
      setBusy(false);
      if (job.lesson_id) { loadSource(job.lesson_id); refreshEditor(job.lesson_id); loadRecent(); }
    }
    if (finished) {
      const st = String(job.mp4_state || "");
      if (job.mp4 || !st || st.startsWith("failed")) {   // MP4 recorded in the background: done waiting
        if (st.startsWith("failed")) $("mp4btn").textContent = "MP4 failed";
        if (job.mp4 && job.lesson_id) { loadSource(job.lesson_id); loadRecent(); }
        return;
      }
    }
    await sleep(finished ? 1200 : job.lesson_id ? 500 : 250);      // fast until the first slide is on screen
    try { job = await api(`/api/jobs/${job.id}`); } catch (e) { $("err").textContent = "Lost contact with the app. Is the black window still open?"; setBusy(false); return; }
  }
}
async function startJob(url, body) {
  setBusy(true); $("err").textContent = ""; $("choice").hidden = true;
  try { pollJob(await api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })); }
  catch (e) {
    setBusy(false);
    if ((e.status === 409 || e.status === 400) && e.detail && e.detail.analysis) showChoice(e.detail.analysis, true);
    else $("err").textContent = e.message;
  }
}
function generate(confirm) {
  if (busy) return;
  const topic = $("topic").value.trim(); if (!topic) { $("topic").focus(); return; }
  startJob("/api/generate", { topic, level, language: $("language").value, seconds: +$("seconds").value,
    gender: $("gender").value, speed: +$("speed").value, confirm: !!confirm });
}
$("f").onsubmit = e => { e.preventDefault(); generate(false); };
$("revoice").onclick = () => startJob(`/api/lessons/${lessonId}/revoice`, { language: $("relang").value, gender: $("regender").value, speed: +$("speed").value });

function showPlayer(id, autoplay) {
  lessonId = id;
  $("view").outerHTML = `<iframe id="view" class="stage-frame" title="Lesson player" src="player.html?id=${id}&autoplay=${autoplay ? 1 : 0}&ts=${Date.now()}" allow="autoplay"></iframe>`;
  $("bar").hidden = false; $("editor").hidden = true; $("source").innerHTML = "";
  $("mp4").href = `/lessons/${id}/lesson.mp4`; $("srt").href = `/lessons/${id}/captions.srt`;
  $("mp4btn").disabled = true; $("mp4btn").textContent = "MP4 rendering…";
}
async function loadSource(id) {
  try {
    const m = await api(`/api/lessons/${id}/meta`);
    const label = m.source === "fallback" || m.source === "library" ? `<span class="chip warn">Offline lesson (the AI was unavailable) · checked notes</span>`
      : m.kb ? `<span class="chip ok">✓ Built on checked offline notes</span>` : `<span class="chip warn">⚠ From the AI's general knowledge: not verified</span>`;
    $("source").innerHTML = `${label} <span class="chip">${esc(m.level)} · ${esc(m.language)} · ${Math.round(m.duration)} s</span>` +
      (m.mp4 ? ` <span class="chip">MP4 ${m.mp4.size_mb} MB</span>` : "");
    if (m.mp4) { $("mp4btn").disabled = false; $("mp4btn").textContent = "⬇ Download MP4"; }
  } catch (e) {}
}
async function openLesson(id) {
  location.hash = "#learn";
  await sleep(30);
  showPlayer(id, false); loadSource(id); refreshEditor(id);
}

// teacher edit
async function refreshEditor(id) {
  try { timeline = await api(`/lessons/${id}/timeline.json?ts=${Date.now()}`); } catch (e) { return; }
  $("sceneSel").innerHTML = timeline.scenes.map((s, i) => `<option value="${i}">${i + 1}. ${esc(s.data.heading)}</option>`).join("");
  renderSceneForm(); $("editor").hidden = false;
}
function renderSceneForm() {
  const s = timeline.scenes[+$("sceneSel").value];
  $("sceneForm").innerHTML = `<label class="lab">Heading</label><input id="e_heading" class="field">` +
    s.beats.map((b, i) => `<label class="lab">Narration ${i + 1}</label><textarea id="e_b${i}" class="field"></textarea>`).join("");
  $("e_heading").value = s.data.heading;
  s.beats.forEach((b, i) => $("e_b" + i).value = b.text);
}
$("sceneSel").onchange = renderSceneForm;
$("saveScene").onclick = () => {
  const i = +$("sceneSel").value, s = timeline.scenes[i];
  const scene = { ...s.data, heading: $("e_heading").value, narration: s.beats.map((b, k) => ({ text: $("e_b" + k).value, focus: b.focus })) };
  startJob(`/api/lessons/${lessonId}/scenes/${i}`, { scene });
};

// ================================================================ HISTORY
let hist = [];
const SOURCE = { ai: "AI lesson", cache: "from cache", fallback: "offline lesson", revoice: "revoiced", library: "offline library", edit: "edited" };
async function loadHistory() { try { hist = await api("/api/history"); } catch (e) { hist = []; } renderHistory(); }
async function loadRecent() {
  try { hist = await api("/api/history"); } catch (e) { return; }
  $("recent").innerHTML = hist.slice(0, 4).map(h => `<button class="mini" data-id="${h.id}"><span>🎬</span><span><b>${esc(h.title)}</b><small>${h.level} · ${h.language} · ${Math.round(h.duration || 0)} s · ${ago(h.created)}</small></span></button>`).join("")
    || '<div class="empty">Lessons you make appear here.</div>';
}
$("recent").onclick = e => { const b = e.target.closest("[data-id]"); if (b) openLesson(b.dataset.id); };
function renderHistory() {
  const q = $("hsearch").value.toLowerCase();
  const items = hist.filter(h => !q || `${h.title} ${h.topic} ${h.language} ${h.level}`.toLowerCase().includes(q));
  $("clearAll").disabled = !hist.length;
  $("hist").innerHTML = items.length ? items.map(h => `<div class="hitem"><h4>${esc(h.title)}</h4>
    <div class="meta"><span class="chip">${esc(h.level)}</span><span class="chip">${esc(h.language)}</span><span class="chip">${Math.round(h.duration || 0)} s</span><span class="chip">${SOURCE[h.source] || esc(h.source)}</span><span>${ago(h.created)}</span></div>
    <div class="bt"><button class="btn small" data-open="${h.id}">▶ Play</button>${h.mp4 ? `<a class="btn small ghost" href="/lessons/${h.id}/lesson.mp4" download>⬇ MP4</a>` : ""}
    <span style="flex:1"></span><button class="btn small danger" data-del="${h.id}" aria-label="Delete ${esc(h.title)}">🗑 Delete</button></div></div>`).join("")
    : `<div class="empty">${hist.length ? "No lessons match your search." : "No lessons yet. Make one in Learn Mode."}</div>`;
}
$("hsearch").oninput = renderHistory;
$("hist").onclick = async e => {
  const o = e.target.closest("[data-open]"), d = e.target.closest("[data-del]");
  if (o) openLesson(o.dataset.open);
  if (d) {
    const h = hist.find(x => x.id === d.dataset.del);
    if (await confirmBox("Delete this lesson?", `“${h ? h.title : ""}” and its video will be removed permanently.`)) {
      try { await api(`/api/lessons/${d.dataset.del}`, { method: "DELETE" }); toast("Lesson deleted"); } catch (er) { toast(er.message); }
      loadHistory();
    }
  }
};
$("clearAll").onclick = async () => {
  if (await confirmBox("Clear all history?", `All ${hist.length} lessons and their videos will be removed permanently.`, "Clear all")) {
    try { const r = await api("/api/history", { method: "DELETE" }); toast(`${r.deleted} lessons deleted`); } catch (er) { toast(er.message); }
    loadHistory();
  }
};

// ================================================================ EXAM
const exam = { doc: null, id: null, data: null, answers: {}, marked: new Set(), cur: 0, deadline: 0, started: 0, tick: null, results: null };
let difficulty = "medium";
$("diff").onclick = e => { const b = e.target.closest("button"); if (!b) return; difficulty = b.dataset.v; [...$("diff").children].forEach(x => x.classList.toggle("on", x === b)); };
const drop = $("drop");
drop.onclick = e => { if (e.target.id !== "file") $("file").click(); };
drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file").click(); } };
["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) upload(f); });
$("file").onchange = () => { if ($("file").files[0]) upload($("file").files[0]); };
function upload(file) {
  $("exErr").textContent = ""; $("docbox").innerHTML = ""; $("startExam").disabled = true;
  if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") { $("exErr").textContent = "Please choose a PDF file."; return; }
  const bar = $("upbar"); bar.hidden = false; bar.firstElementChild.style.width = "0";
  const x = new XMLHttpRequest();
  x.open("POST", "/api/exam/upload?name=" + encodeURIComponent(file.name));
  x.setRequestHeader("Content-Type", "application/pdf");
  x.upload.onprogress = e => { if (e.lengthComputable) bar.firstElementChild.style.width = (90 * e.loaded / e.total) + "%"; };
  x.onload = () => {
    bar.firstElementChild.style.width = "100%"; setTimeout(() => bar.hidden = true, 500);
    let j = {}; try { j = JSON.parse(x.responseText); } catch (e) {}
    if (x.status !== 200) { $("exErr").textContent = j.detail || "Upload failed."; return; }
    exam.doc = j;
    $("docbox").innerHTML = `<div class="doc"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>
      <div><b>${esc(j.name)}</b><div style="color:var(--muted);font-size:14px">${j.pages} page(s) · ${j.words} words · ${j.sections.length} topic(s) found</div>
      <div class="chips">${j.sections.map(s => `<span class="chip">${esc(s.title)}</span>`).join("")}</div>
      <div class="chips">${j.key_terms.slice(0, 10).map(k => `<span class="chip blu">${esc(k)}</span>`).join("")}</div></div></div>`;
    $("startExam").disabled = false;
  };
  x.onerror = () => { bar.hidden = true; $("exErr").textContent = "Upload failed. Is the app still running?"; };
  x.send(file);
}
$("startExam").onclick = async () => {
  const types = [$("tMcq").checked && "mcq", $("tTf").checked && "tf"].filter(Boolean);
  if (!types.length) { $("exErr").textContent = "Choose at least one question type."; return; }
  $("startExam").disabled = true; $("exErr").textContent = ""; $("exDetail").textContent = "Preparing questions…";
  try {
    let job = await api("/api/exam/create", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: exam.doc.id, count: +$("qcount").value, difficulty, types, language: $("exLang").value, minutes: +$("timer").value, use_ai: $("useAi").checked }) });
    while (job.status !== "done" && job.status !== "error") {
      $("exDetail").textContent = job.detail || "Preparing questions…";
      await sleep(700); job = await api(`/api/jobs/${job.id}`);
    }
    if (job.status === "error") throw new Error(job.error);
    $("exDetail").textContent = "";
    await beginExam(job.lesson_id);
  } catch (e) { $("exErr").textContent = e.message; }
  $("startExam").disabled = false;
};
async function beginExam(id) {
  exam.id = id; exam.data = await api(`/api/exam/${id}`);
  exam.answers = {}; exam.marked = new Set(); exam.cur = 0; exam.started = Date.now();
  const mins = exam.data.settings.minutes;
  exam.deadline = mins ? Date.now() + mins * 60000 : 0;
  clearInterval(exam.tick);
  if (exam.deadline) exam.tick = setInterval(clock, 500);
  $("clock").textContent = "";
  $("testTitle").textContent = exam.data.doc_name.replace(/\.pdf$/i, "");
  $("testInfo").textContent = `${exam.data.questions.length} questions · ${exam.data.settings.difficulty}`;
  location.hash = "#test";
  renderQ();
}
function clock() {
  const left = Math.max(0, (exam.deadline - Date.now()) / 1000);
  $("clock").textContent = "⏱ " + fmtTime(left); $("clock").classList.toggle("low", left < 60);
  if (left <= 0) { clearInterval(exam.tick); submitExam(true); }
}
function renderQ() {
  const qs = exam.data.questions, q = qs[exam.cur];
  $("palette").innerHTML = qs.map((x, i) => `<button class="${exam.answers[x.id] !== undefined ? "ans" : ""} ${exam.marked.has(x.id) ? "rev" : ""} ${i === exam.cur ? "cur" : ""}" data-i="${i}" aria-label="Question ${i + 1}">${i + 1}</button>`).join("");
  $("qnum").textContent = `Question ${exam.cur + 1} of ${qs.length} · ${q.type === "tf" ? "True / False" : "Multiple choice"}` + (q.support === "inferred" ? " · inferred from the notes" : "");
  $("qtext").textContent = q.question;
  $("qopts").innerHTML = q.options.map((o, i) => `<button class="opt ${exam.answers[q.id] === i ? "sel" : ""}" role="radio" aria-checked="${exam.answers[q.id] === i}" data-o="${i}"><span class="l">${String.fromCharCode(65 + i)}</span><span>${esc(o)}</span></button>`).join("");
  $("prevQ").disabled = exam.cur === 0;
  $("nextQ").textContent = exam.cur === qs.length - 1 ? "Finish →" : "Next →";
  $("markQ").textContent = exam.marked.has(q.id) ? "★ Marked for review" : "☆ Mark for review";
}
$("palette").onclick = e => { const b = e.target.closest("[data-i]"); if (b) { exam.cur = +b.dataset.i; renderQ(); } };
$("qopts").onclick = e => { const b = e.target.closest("[data-o]"); if (!b) return; exam.answers[exam.data.questions[exam.cur].id] = +b.dataset.o; renderQ(); };
$("prevQ").onclick = () => { if (exam.cur > 0) { exam.cur--; renderQ(); } };
$("nextQ").onclick = () => { if (exam.cur < exam.data.questions.length - 1) { exam.cur++; renderQ(); } else submitExam(false); };
$("markQ").onclick = () => { const id = exam.data.questions[exam.cur].id; exam.marked.has(id) ? exam.marked.delete(id) : exam.marked.add(id); renderQ(); };
addEventListener("keydown", e => {
  if ($("p-test").hidden || !$("modal").hidden) return;
  if (e.key === "ArrowRight") $("nextQ").click(); if (e.key === "ArrowLeft") $("prevQ").click();
  const n = "1234".indexOf(e.key); if (n >= 0 && n < exam.data.questions[exam.cur].options.length) { exam.answers[exam.data.questions[exam.cur].id] = n; renderQ(); }
});
$("submitBtn").onclick = () => submitExam(false);
async function submitExam(timeUp) {
  const qs = exam.data.questions, left = qs.filter(q => exam.answers[q.id] === undefined).length;
  if (!timeUp && !(await confirmBox("Submit the test?", left ? `${left} question(s) are not answered yet. Submit anyway?` : "You have answered every question.", "Submit"))) return;
  clearInterval(exam.tick);
  const answers = {}; for (const [k, v] of Object.entries(exam.answers)) answers[k] = v;
  exam.results = await api(`/api/exam/${exam.id}/submit`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers, seconds_taken: Math.round((Date.now() - exam.started) / 1000) }) });
  if (timeUp) toast("Time is up: your test was submitted");
  location.hash = "#results"; renderResults();
}
function renderResults() {
  const r = exam.results, pct = r.percent, C = 2 * Math.PI * 80, col = pct >= 75 ? "var(--ok)" : pct >= 50 ? "var(--warn)" : "var(--bad)";
  $("ring").innerHTML = `<circle cx="100" cy="100" r="80" fill="none" stroke="var(--bg2)" stroke-width="18"/>
    <circle cx="100" cy="100" r="80" fill="none" stroke="${col}" stroke-width="18" stroke-linecap="round" stroke-dasharray="${C * pct / 100} ${C}" transform="rotate(-90 100 100)"/>
    <text x="100" y="112" text-anchor="middle" font-size="44">${pct}%</text>`;
  $("scoreLine").textContent = `${r.score} / ${r.total} correct`;
  $("scoreSub").textContent = `${r.answered} answered · ${r.total - r.score} incorrect or skipped` + (r.seconds_taken ? ` · time ${fmtTime(r.seconds_taken)}` : "") +
    (r.attempts.length > 1 ? ` · attempt ${r.attempts.length}, best ${Math.max(...r.attempts.map(a => a.percent))}%` : "");
  $("secbars").innerHTML = r.sections.map(s => `<div class="secbar ${s.percent < 60 ? "weak" : ""}"><div><div style="font-weight:650;margin-bottom:4px">${esc(s.title)}</div><div class="bar"><span style="width:${s.percent}%"></span></div></div><b>${s.correct}/${s.total}</b></div>`).join("");
  $("weakBox").innerHTML = r.weak.length ? `<b>Revise these topics:</b><div class="weak-list">${r.weak.map(w => `<button class="btn small" data-learn="${esc(w)}">📘 Learn: ${esc(w)}</button>`).join("")}</div>`
    : `<div class="okmsg">Great work: no weak topics in this test.</div>`;
  renderReview(true);
}
function renderReview(wrongOnly) {
  const rows = exam.results.rows.filter(x => !wrongOnly || !x.correct);
  $("review").innerHTML = rows.length ? rows.map(x => `<div class="rv ${x.correct ? "" : "wrong"}">
    <div style="display:flex;gap:6px;flex-wrap:wrap"><span class="chip ${x.correct ? "ok" : "bad"}">${x.correct ? "✓ Correct" : x.your === null ? "Not answered" : "✗ Incorrect"}</span><span class="chip">${esc(x.section)} · page ${x.page}</span>${x.support === "inferred" ? '<span class="chip warn">inferred from the notes</span>' : '<span class="chip blu">supported by the notes</span>'}</div>
    <div class="q">${esc(x.question)}</div>
    <div class="a">${x.your !== null && !x.correct ? `Your answer: <b>${esc(x.options[x.your])}</b><br>` : ""}Correct answer: <b>${esc(x.options[x.answer])}</b><br>${esc(x.explanation)}</div>
    ${x.evidence ? `<blockquote>📄 “${esc(x.evidence)}”</blockquote>` : ""}</div>`).join("")
    : `<div class="okmsg">${wrongOnly ? "No incorrect answers to review." : ""}</div>`;
}
$("showWrong").onclick = () => renderReview(true);
$("showAll").onclick = () => renderReview(false);
$("retake").onclick = () => beginExam(exam.id);
$("weakBox").onclick = e => { const b = e.target.closest("[data-learn]"); if (!b) return; location.hash = "#learn"; setTimeout(() => { $("topic").value = b.dataset.learn; understand(); $("topic").focus(); }, 60); };
async function loadPastExams() {
  let xs = []; try { xs = await api("/api/exams"); } catch (e) {}
  $("pastExams").innerHTML = xs.length ? xs.map(x => `<div class="hitem"><h4>${esc(x.doc_name)}</h4><div class="meta"><span class="chip">${x.count} questions</span>
    <span class="chip ${x.best >= 75 ? "ok" : x.best >= 50 ? "warn" : x.best !== null ? "bad" : ""}">${x.best !== null ? "best " + x.best + "%" : "not attempted"}</span><span>${x.attempts} attempt(s) · ${ago(x.created)}</span></div>
    <div class="bt"><button class="btn small" data-take="${x.id}" style="background:var(--violet)">▶ Take again</button><span style="flex:1"></span><button class="btn small danger" data-xdel="${x.id}">🗑</button></div></div>`).join("")
    : '<div class="empty">Your tests and scores will appear here.</div>';
}
$("pastExams").onclick = async e => {
  const t = e.target.closest("[data-take]"), d = e.target.closest("[data-xdel]");
  if (t) beginExam(t.dataset.take);
  if (d && await confirmBox("Delete this test?", "Its questions and scores will be removed.")) { await api(`/api/exam/${d.dataset.xdel}`, { method: "DELETE" }); loadPastExams(); }
};

warm();
route();
