// Blu Visual Teacher player.
// Everything on screen is a pure function of time t (seconds). The live player drives t from the
// audio clock; the MP4 exporter calls window.renderAt(t) frame by frame. Same code, perfect sync.
// Visuals come only from these components; lesson data is never executed.

const W = 1280, H = 720;
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const ease = x => { x = clamp(x); return x < .5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2; };
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SVG = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, parent) {
  const e = tag.startsWith("svg:") ? document.createElementNS(SVG, tag.slice(4)) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") e.textContent = v; else if (k === "html") e.innerHTML = v; else e.setAttribute(k, v);
  }
  if (parent) parent.appendChild(e);
  return e;
}

// idle motion (floating drawings, flowing particles, pulses) moves every frame in the live player, but
// only 4 times a second while the MP4 is recorded: identical frames are reused, so export is much faster
const IDLE_HZ = 4;
const idle = t => (document.body.classList.contains("export") ? Math.floor(t * IDLE_HZ) / IDLE_HZ : t);

// beat helpers ---------------------------------------------------------------
function activeBeat(beats, t) {
  let idx = -1;
  for (let i = 0; i < beats.length; i++) if (t >= beats[i].start - 0.05) idx = i;
  return idx;
}
// when does item k first get focus? (null if never)
function focusTime(beats, k) {
  const b = beats.find(b => b.focus === k);
  return b ? b.start : null;
}

// drawing library for "illustration" scenes ------------------------------------
// Each drawing fits a 100 x 100 box centred on (0, 0). Static markup written here, never lesson data.
// Names must match backend/schema.py ART.
const g = (body) => body;
const molecule = (balls, formula) => balls.map(([x, y, r, c]) =>
  `<circle cx="${x}" cy="${y}" r="${r}" fill="${c}" stroke="#1F2937" stroke-width="2"/>`).join("") +
  `<text x="0" y="40" text-anchor="middle" font-size="17" font-weight="800" fill="#1F2937">${formula}</text>`;
const gearPath = (() => {
  let d = "";
  for (let i = 0; i < 16; i++) {
    const a = i * Math.PI / 8, r = i % 2 ? 26 : 36;
    d += (i ? "L" : "M") + (r * Math.cos(a)).toFixed(1) + " " + (r * Math.sin(a)).toFixed(1);
  }
  return d + "Z";
})();
const ART = {
  sun: g(`<g stroke="#F59E0B" stroke-width="6" stroke-linecap="round">${[0, 1, 2, 3, 4, 5, 6, 7].map(i => {
    const a = i * Math.PI / 4; return `<line x1="${30 * Math.cos(a)}" y1="${30 * Math.sin(a)}" x2="${44 * Math.cos(a)}" y2="${44 * Math.sin(a)}"/>`;
  }).join("")}</g><circle r="22" fill="#FDB813"/>`),
  plant: g(`<rect x="-46" y="12" width="92" height="5" rx="2" fill="#8B5E3C"/>
    <path d="M0 15 C -4 27 -14 31 -24 42 M0 15 C 2 29 0 35 2 47 M0 15 C 6 27 14 33 24 42" stroke="#A0522D" stroke-width="3" fill="none"/>
    <path d="M0 15 C 0 -8 2 -24 0 -42" stroke="#2E8B57" stroke-width="5" fill="none"/>
    <path d="M0 -10 C -20 -26 -40 -18 -44 -4 C -28 0 -12 -2 0 -10 Z" fill="#34A853"/>
    <path d="M0 -24 C 20 -40 40 -32 44 -18 C 28 -14 12 -16 0 -24 Z" fill="#2E9E4F"/>
    <path d="M0 -40 C -10 -48 -4 -54 0 -56 C 4 -54 10 -48 0 -40 Z" fill="#34A853"/>`),
  leaf: g(`<path d="M-36 32 C -42 -10 -10 -40 38 -38 C 36 8 6 36 -36 32 Z" fill="#34A853"/><path d="M-34 30 L 30 -30" stroke="#1E7B3A" stroke-width="3"/>`),
  tree: g(`<rect x="-6" y="0" width="12" height="42" fill="#8B5E3C"/><circle cy="-14" r="26" fill="#2E9E4F"/><circle cx="-20" cy="-2" r="18" fill="#34A853"/><circle cx="20" cy="-2" r="18" fill="#34A853"/>`),
  water: g(`<path d="M0 -40 C 14 -20 27 -6 27 12 A27 27 0 0 1 -27 12 C -27 -6 -14 -20 0 -40 Z" fill="#3B82F6"/><ellipse cx="-9" cy="8" rx="5" ry="9" fill="#fff" opacity=".55"/>`),
  rain: g(`<circle cx="-14" cy="-14" r="15" fill="#94A3B8"/><circle cx="6" cy="-22" r="18" fill="#94A3B8"/><circle cx="22" cy="-12" r="13" fill="#94A3B8"/><rect x="-30" y="-14" width="64" height="16" rx="8" fill="#94A3B8"/>
    <g stroke="#3B82F6" stroke-width="5" stroke-linecap="round"><line x1="-16" y1="12" x2="-22" y2="28"/><line x1="2" y1="14" x2="-4" y2="32"/><line x1="20" y1="12" x2="14" y2="28"/></g>`),
  cloud: g(`<circle cx="-18" cy="4" r="17" fill="#CBD5E1"/><circle cx="2" cy="-8" r="22" fill="#E2E8F0"/><circle cx="22" cy="4" r="16" fill="#CBD5E1"/><rect x="-35" y="2" width="72" height="20" rx="10" fill="#E2E8F0"/>`),
  sea: g(`<rect x="-44" y="-8" width="88" height="40" rx="10" fill="#3B82F6"/><path d="M-40 4 q10 -8 20 0 t20 0 t20 0 t20 0" stroke="#fff" stroke-width="3" fill="none"/><path d="M-40 18 q10 -8 20 0 t20 0 t20 0 t20 0" stroke="#BFDBFE" stroke-width="3" fill="none"/>`),
  mountain: g(`<polygon points="-46,34 -12,-28 6,2 18,-14 46,34" fill="#94A3B8"/><polygon points="-12,-28 -21,-12 -3,-12" fill="#fff"/><path d="M6 34 C 0 24 14 18 8 8" stroke="#3B82F6" stroke-width="5" fill="none"/>`),
  snow: g(`<g stroke="#60A5FA" stroke-width="5" stroke-linecap="round">${[0, 1, 2].map(i => {
    const a = i * Math.PI / 3; return `<line x1="${-34 * Math.cos(a)}" y1="${-34 * Math.sin(a)}" x2="${34 * Math.cos(a)}" y2="${34 * Math.sin(a)}"/>`;
  }).join("")}</g><circle r="7" fill="#DBEAFE"/>`),
  wind: g(`<g stroke="#94A3B8" stroke-width="6" fill="none" stroke-linecap="round"><path d="M-40 -14 H 16 a10 10 0 1 0 -10 -10"/><path d="M-40 4 H 30 a10 10 0 1 1 -10 10"/><path d="M-40 22 H 4"/></g>`),
  heat: g(`<path d="M0 -42 C 18 -18 30 -2 26 16 C 22 34 -22 34 -26 16 C -28 2 -16 -6 -10 -22 C -6 -10 0 -8 4 -4 C 6 -18 2 -30 0 -42 Z" fill="#F97316"/><path d="M0 0 C 10 10 14 18 10 26 C 6 32 -8 32 -11 24 C -13 16 -6 10 0 0 Z" fill="#FDE047"/>`),
  co2: g(molecule([[-24, 0, 11, "#EF4444"], [0, 0, 14, "#374151"], [24, 0, 11, "#EF4444"]], "CO₂")),
  o2: g(molecule([[-11, 0, 13, "#EF4444"], [11, 0, 13, "#EF4444"]], "O₂")),
  h2o: g(molecule([[0, -4, 14, "#EF4444"], [-18, 10, 9, "#F9FAFB"], [18, 10, 9, "#F9FAFB"]], "H₂O")),
  glucose: g(`<polygon points="0,-32 28,-16 28,16 0,32 -28,16 -28,-16" fill="#FEF3C7" stroke="#F59E0B" stroke-width="5"/><text y="7" text-anchor="middle" font-size="15" font-weight="800" fill="#92400E">C₆H₁₂O₆</text>`),
  molecule: g(`<line x1="-22" y1="12" x2="0" y2="-10" stroke="#475569" stroke-width="5"/><line x1="0" y1="-10" x2="24" y2="12" stroke="#475569" stroke-width="5"/><circle cx="0" cy="-10" r="15" fill="#6366F1"/><circle cx="-22" cy="12" r="11" fill="#22C55E"/><circle cx="24" cy="12" r="11" fill="#F59E0B"/>`),
  atom: g(`<g fill="none" stroke="#3B82F6" stroke-width="3"><ellipse rx="42" ry="15"/><ellipse rx="42" ry="15" transform="rotate(60)"/><ellipse rx="42" ry="15" transform="rotate(-60)"/></g><circle r="9" fill="#EF4444"/><circle cx="42" r="5" fill="#1D4ED8"/><circle cx="-21" cy="-36" r="5" fill="#1D4ED8"/>`),
  beaker: g(`<path d="M-26 -36 V 30 a8 8 0 0 0 8 8 H 18 a8 8 0 0 0 8 -8 V -36" fill="#F8FAFC" stroke="#64748B" stroke-width="4"/><path d="M-24 2 H 24 V 30 a6 6 0 0 1 -6 6 H -18 a6 6 0 0 1 -6 -6 Z" fill="#A78BFA"/><line x1="-32" y1="-36" x2="32" y2="-36" stroke="#64748B" stroke-width="4"/>`),
  flask: g(`<path d="M-9 -40 V -12 L -34 34 H 34 L 9 -12 V -40" fill="#F8FAFC" stroke="#64748B" stroke-width="4" stroke-linejoin="round"/><path d="M-22 12 H 22 L 31 31 H -31 Z" fill="#34D399"/><circle cx="-4" cy="20" r="3" fill="#fff"/><circle cx="8" cy="26" r="2" fill="#fff"/>`),
  salt: g(`<g stroke="#9CA3AF" stroke-width="3" fill="#F3F4F6"><rect x="-34" y="-2" width="30" height="30"/><rect x="2" y="4" width="26" height="26"/><rect x="-14" y="-30" width="28" height="28"/></g>`),
  battery: g(`<rect x="-40" y="-20" width="74" height="40" rx="6" fill="#FBBF24" stroke="#1F2937" stroke-width="4"/><rect x="34" y="-9" width="8" height="18" fill="#1F2937"/><rect x="-40" y="-20" width="26" height="40" rx="6" fill="#1F2937"/><text x="10" y="9" font-size="26" font-weight="900" text-anchor="middle" fill="#1F2937">+</text>`),
  bulb: g(`<circle cy="-10" r="27" fill="#FDE68A" stroke="#F59E0B" stroke-width="4"/><path d="M-8 -6 l4 -8 l4 8 l4 -8 l4 8" stroke="#B45309" stroke-width="3" fill="none"/><rect x="-14" y="16" width="28" height="20" rx="3" fill="#9CA3AF"/><line x1="-14" y1="24" x2="14" y2="24" stroke="#6B7280" stroke-width="2"/>`),
  resistor: g(`<path d="M-46 0 H -26 l6 -14 l10 28 l10 -28 l10 28 l10 -28 l6 14 H 46" stroke="#1F2937" stroke-width="5" fill="none" stroke-linejoin="round"/>`),
  magnet: g(`<path d="M-24 -34 V 6 a24 24 0 0 0 48 0 V -34" stroke="#EF4444" stroke-width="18" fill="none"/><rect x="-33" y="-40" width="18" height="14" fill="#E5E7EB"/><rect x="15" y="-40" width="18" height="14" fill="#E5E7EB"/>`),
  ball: g(`<g stroke="#94A3B8" stroke-width="4" stroke-linecap="round"><line x1="-46" y1="-10" x2="-28" y2="-10"/><line x1="-44" y1="4" x2="-30" y2="4"/></g><circle cx="6" r="26" fill="#EF4444"/><circle cx="-2" cy="-9" r="7" fill="#fff" opacity=".6"/>`),
  rocket: g(`<path d="M0 -44 C 18 -26 18 6 12 22 H -12 C -18 6 -18 -26 0 -44 Z" fill="#E5E7EB" stroke="#475569" stroke-width="3"/><circle cy="-14" r="8" fill="#3B82F6"/><path d="M-12 10 L -24 26 L -10 22 Z M12 10 L 24 26 L 10 22 Z" fill="#EF4444"/><path d="M-8 24 L 0 44 L 8 24 Z" fill="#F97316"/>`),
  earth: g(`<circle r="36" fill="#3B82F6"/><path d="M-22 -22 C -6 -28 4 -18 -4 -8 C -12 2 -26 -2 -28 -12 Z M6 6 C 20 0 30 10 22 22 C 14 30 2 24 6 6 Z M10 -30 C 18 -30 24 -24 22 -18 C 16 -20 10 -24 10 -30 Z" fill="#22C55E"/>`),
  moon: g(`<circle r="34" fill="#E5E7EB"/><circle cx="-10" cy="-8" r="7" fill="#CBD5E1"/><circle cx="12" cy="10" r="9" fill="#CBD5E1"/><circle cx="8" cy="-16" r="4" fill="#CBD5E1"/>`),
  star: g(`<polygon points="0,-40 10,-13 38,-12 16,6 24,34 0,18 -24,34 -16,6 -38,-12 -10,-13" fill="#FBBF24" stroke="#F59E0B" stroke-width="3" stroke-linejoin="round"/>`),
  heart: g(`<path d="M0 36 C -40 8 -44 -18 -28 -30 C -16 -38 -4 -32 0 -20 C 4 -32 16 -38 28 -30 C 44 -18 40 8 0 36 Z" fill="#E11D48"/><path d="M-20 -18 C -26 -10 -24 -2 -18 4" stroke="#fff" stroke-width="4" fill="none" opacity=".5"/>`),
  lungs: g(`<path d="M-4 -40 V -4 M4 -40 V -4 M-4 -4 L -14 6 M4 -4 L 14 6" stroke="#9D174D" stroke-width="5" fill="none"/><path d="M-10 -22 C -30 -24 -42 4 -38 26 C -36 36 -20 38 -10 30 Z" fill="#F472B6"/><path d="M10 -22 C 30 -24 42 4 38 26 C 36 36 20 38 10 30 Z" fill="#F472B6"/>`),
  brain: g(`<path d="M-4 -34 C -26 -38 -42 -20 -38 0 C -44 16 -28 34 -8 30 C -4 32 -2 32 0 30 V -32 Z M4 -34 C 26 -38 42 -20 38 0 C 44 16 28 34 8 30 C 4 32 2 32 0 30 V -32 Z" fill="#F9A8D4" stroke="#DB2777" stroke-width="3"/><path d="M-26 -8 C -18 -14 -12 -6 -18 2 M22 -10 C 14 -16 10 -6 16 2 M-20 16 C -12 12 -8 20 -14 24" stroke="#DB2777" stroke-width="3" fill="none"/>`),
  person: g(`<circle cy="-24" r="15" fill="#6366F1"/><path d="M-26 40 V 10 C -26 -6 -14 -6 0 -6 C 14 -6 26 -6 26 10 V 40 Z" fill="#6366F1"/>`),
  blood: g(`<path d="M-10 -40 C 2 -22 12 -10 12 4 A22 22 0 0 1 -32 4 C -32 -10 -22 -22 -10 -40 Z" fill="#DC2626"/><circle cx="22" cy="18" r="13" fill="#EF4444"/><circle cx="22" cy="18" r="5" fill="#B91C1C"/><circle cx="30" cy="-12" r="9" fill="#EF4444"/>`),
  cell: g(`<ellipse rx="42" ry="34" fill="#D1FAE5" stroke="#10B981" stroke-width="4"/><circle cx="6" cy="-2" r="13" fill="#6EE7B7" stroke="#059669" stroke-width="3"/><circle cx="-22" cy="12" r="4" fill="#34D399"/><circle cx="24" cy="16" r="3" fill="#34D399"/>`),
  dna: g(`<path d="M-14 -42 C 26 -24 -26 -4 14 14 C 34 22 -6 40 -14 42" stroke="#6366F1" stroke-width="5" fill="none"/><path d="M14 -42 C -26 -24 26 -4 -14 14 C -34 22 6 40 14 42" stroke="#EC4899" stroke-width="5" fill="none"/><g stroke="#94A3B8" stroke-width="3"><line x1="-8" y1="-32" x2="8" y2="-32"/><line x1="-6" y1="-6" x2="6" y2="-6"/><line x1="-8" y1="26" x2="8" y2="26"/></g>`),
  virus: g(`<g stroke="#7C3AED" stroke-width="4">${[0, 1, 2, 3, 4, 5, 6, 7].map(i => {
    const a = i * Math.PI / 4; return `<line x1="${24 * Math.cos(a)}" y1="${24 * Math.sin(a)}" x2="${38 * Math.cos(a)}" y2="${38 * Math.sin(a)}"/><circle cx="${40 * Math.cos(a)}" cy="${40 * Math.sin(a)}" r="4" fill="#7C3AED"/>`;
  }).join("")}</g><circle r="25" fill="#C4B5FD"/>`),
  food: g(`<path d="M-40 0 H 40 C 38 24 22 36 0 36 C -22 36 -38 24 -40 0 Z" fill="#F59E0B"/><ellipse cy="0" rx="40" ry="8" fill="#FDE68A"/><path d="M-12 -12 c-6 -8 6 -12 0 -22 M8 -12 c-6 -8 6 -12 0 -22" stroke="#CBD5E1" stroke-width="4" fill="none"/>`),
  computer: g(`<rect x="-42" y="-34" width="84" height="54" rx="6" fill="#1F2937"/><rect x="-36" y="-28" width="72" height="42" rx="3" fill="#60A5FA"/><rect x="-6" y="20" width="12" height="12" fill="#6B7280"/><rect x="-22" y="32" width="44" height="6" rx="3" fill="#6B7280"/>`),
  code: g(`<rect x="-44" y="-32" width="88" height="64" rx="10" fill="#14192A"/><text y="12" text-anchor="middle" font-size="34" font-weight="800" fill="#7DD3FC" font-family="Noto Sans Mono, monospace">&lt;/&gt;</text>`),
  gear: g(`<path d="${gearPath}" fill="#64748B"/><circle r="11" fill="#F8FAFC"/>`),
  clock: g(`<circle r="38" fill="#fff" stroke="#1F2937" stroke-width="5"/><line x1="0" y1="0" x2="0" y2="-24" stroke="#1F2937" stroke-width="5" stroke-linecap="round"/><line x1="0" y1="0" x2="16" y2="8" stroke="#EF4444" stroke-width="4" stroke-linecap="round"/><circle r="4" fill="#1F2937"/>`),
  book: g(`<path d="M0 -26 C -14 -34 -30 -34 -42 -28 V 30 C -30 24 -14 24 0 32 Z" fill="#60A5FA" stroke="#1D4ED8" stroke-width="3"/><path d="M0 -26 C 14 -34 30 -34 42 -28 V 30 C 30 24 14 24 0 32 Z" fill="#93C5FD" stroke="#1D4ED8" stroke-width="3"/>`),
  coin: g(`<circle r="36" fill="#FBBF24" stroke="#D97706" stroke-width="5"/><circle r="26" fill="none" stroke="#D97706" stroke-width="2"/><text y="13" text-anchor="middle" font-size="36" font-weight="800" fill="#92400E">₹</text>`),
  factory: g(`<path d="M-44 36 V -2 L -20 -16 V -2 L 4 -16 V -2 L 28 -16 V 36 Z" fill="#94A3B8"/><rect x="30" y="-34" width="12" height="70" fill="#64748B"/><circle cx="38" cy="-42" r="7" fill="#CBD5E1"/><circle cx="28" cy="-46" r="5" fill="#E2E8F0"/><rect x="-36" y="12" width="12" height="12" fill="#FDE68A"/><rect x="-12" y="12" width="12" height="12" fill="#FDE68A"/>`),
  house: g(`<polygon points="-40,-2 0,-36 40,-2" fill="#EF4444"/><rect x="-30" y="-4" width="60" height="40" fill="#FDE68A"/><rect x="-8" y="12" width="16" height="24" fill="#92400E"/>`),
  flag: g(`<rect x="-32" y="-40" width="5" height="80" fill="#475569"/><path d="M-27 -38 H 36 L 26 -20 L 36 -2 H -27 Z" fill="#2F6FED"/>`),
  dot: g(`<circle r="30" fill="#E4EDFF" stroke="#2F6FED" stroke-width="4"/><circle r="10" fill="#2F6FED"/>`),
};
// natural places: sky things go high, ground and water things go low
const ART_TOP = new Set(["sun", "cloud", "rain", "snow", "wind", "star", "moon", "o2", "rocket"]);
const ART_LOW = new Set(["water", "sea", "mountain", "salt", "food", "earth", "coin", "house", "factory"]);
const ART_TINT = { sun: "#F59E0B", water: "#3B82F6", sea: "#3B82F6", rain: "#3B82F6", co2: "#475569", o2: "#EF4444",
  glucose: "#F59E0B", heat: "#F97316", blood: "#DC2626", heart: "#E11D48", battery: "#F59E0B", bulb: "#F59E0B" };

// scene components ------------------------------------------------------------
// each: mount(root, scene) -> update(t) where t is the GLOBAL time

const Scenes = {
  title_card(root, sc) {
    const d = sc.data;
    const wrap = el("div", { class: "title-card" }, root);
    // the topic's own drawings pop in and float above the title, so every lesson opens differently
    const arts = (d.art || []).filter(a => ART[a]).slice(0, 3);
    const hero = arts.length ? el("svg:svg", { viewBox: "0 0 600 170", class: "title-art" }, wrap) : null;
    const heroes = arts.map((a, i) => {
      const x = 300 + (i - (arts.length - 1) / 2) * 190;
      const g0 = el("svg:g", {}, hero);
      el("svg:circle", { cx: x, cy: 85, r: 74, class: "title-art-halo" }, g0);
      const gi = el("svg:g", {}, g0);
      gi.innerHTML = ART[a];
      return { g0, gi, x, i };
    });
    const h = el("h1", { text: d.heading }, wrap);
    const bar = el("div", { class: "title-bar" }, wrap);
    const sub = d.subtitle ? el("p", { text: d.subtitle }, wrap) : null;
    return t => {
      const lt = t - sc.start;
      const a = ease(lt / 0.7);
      h.style.opacity = a; h.style.transform = `translateY(${(1 - a) * 30}px)`;
      bar.style.transform = `scaleX(${ease((lt - 0.3) / 0.8)})`;
      if (sub) { const b = ease((lt - 0.6) / 0.6); sub.style.opacity = b; sub.style.transform = `translateY(${(1 - b) * 16}px)`; }
      const it = idle(t) - sc.start;
      heroes.forEach(o => {
        const a = ease((lt - 0.15 - o.i * 0.25) / 0.5);
        const bob = a >= 1 ? Math.sin((it + o.i) * 2.2) * 5 : 0;           // float only after popping in
        o.g0.style.opacity = a;
        o.gi.setAttribute("transform", `translate(${o.x},${85 + bob}) scale(${1.25 * (0.6 + 0.4 * a)}) rotate(${a >= 1 ? Math.sin(it * 1.5 + o.i) * 4 : 0})`);
      });
    };
  },

  code_walkthrough(root, sc) {
    const d = sc.data, lines = d.code.split("\n");
    const wrap = el("div", { class: "code-scene" }, root);
    const panel = el("div", { class: "code-panel" }, wrap);
    el("div", { class: "code-tab", text: d.code_language || "code" }, panel);
    const body = el("div", { class: "code-body" }, panel);
    const hl = el("div", { class: "code-hl" }, body);
    const rows = lines.map((ln, i) => {
      const r = el("div", { class: "code-line" }, body);
      el("span", { class: "ln", text: i + 1 }, r);
      el("span", { class: "src", text: ln || " " }, r);
      return r;
    });
    const side = el("div", { class: "code-side" }, wrap);
    const arrow = el("div", { class: "code-arrow", text: "Line" }, side);
    let out = null, outLines = [];
    if (d.output && d.output.length) {
      out = el("div", { class: "code-out" }, side);
      el("div", { class: "code-out-h", text: "Output" }, out);
      outLines = d.output.map(o => el("div", { class: "code-out-l", text: o }, out));
    }
    // output appears line by line during the last beat (after the code has been explained)
    const outStart = sc.beats.length ? sc.beats[sc.beats.length - 1].start : sc.start + 1;
    // auto-fit: shrink the font for long lines or many lines (panel ~740 x 400 px of code area)
    const maxLen = Math.max(8, ...lines.map(l => l.length));
    const fs = Math.max(15, Math.min(30, 740 / (maxLen * 0.6 + 4), 400 / lines.length / 1.72));
    const LH = Math.round(fs * 1.72), TOP = 18;
    rows.forEach(r => { r.style.height = LH + "px"; r.style.fontSize = fs + "px"; });
    rows.forEach(r => r.firstChild.style.width = Math.round(fs * 2.1) + "px");
    hl.style.height = LH + "px";
    return t => {
      const lt = t - sc.start;
      rows.forEach((r, i) => { const a = ease((lt - 0.1 - i * 0.12) / 0.3); r.style.opacity = a; r.style.transform = `translateX(${(1 - a) * -20}px)`; });
      if (out) {
        out.style.opacity = ease((t - outStart + 0.2) / 0.3);
        outLines.forEach((o, i) => o.style.opacity = ease((t - outStart - i * 0.45) / 0.25));
      }
      const bi = activeBeat(sc.beats, t);
      // focus line: latest beat (at or before now) that has one; slide from the previous one
      let j = -1;
      for (let i = bi; i >= 0; i--) if (sc.beats[i].focus) { j = i; break; }
      const line = j >= 0 ? sc.beats[j].focus : null;
      if (line) {
        let prev = line;
        for (let i = j - 1; i >= 0; i--) if (sc.beats[i].focus) { prev = sc.beats[i].focus; break; }
        const k = ease((t - sc.beats[j].start + 0.05) / 0.35);
        const y = TOP + ((prev - 1) + (line - prev) * k) * LH;
        hl.style.opacity = 1; hl.style.transform = `translateY(${y}px)`;
        rows.forEach((r, i) => r.classList.toggle("dim", i + 1 !== line));
        arrow.style.opacity = 1; arrow.textContent = `Line ${line}`;
        arrow.style.transform = `translateY(${y + 40 + (LH - 52) / 2}px)`;
      } else { hl.style.opacity = 0; arrow.style.opacity = 0; rows.forEach(r => r.classList.remove("dim")); }
    };
  },

  diagram(root, sc) {
    const d = sc.data, n = d.items.length;
    const svg = el("svg:svg", { viewBox: `0 0 ${W} 470`, class: "diagram" }, root);
    const defs = el("svg:defs", {}, svg);
    const mk = el("svg:marker", { id: `ah${sc.index}`, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" }, defs);
    el("svg:path", { d: "M0,0 L10,5 L0,10 z", class: "arrow-head" }, mk);
    // positions
    const icons = d.icons || [], elabels = d.edge_labels || [];
    const hasIcons = icons.some(Boolean), hasLabels = elabels.some(Boolean) && d.layout !== "stack";
    let pos = [], bw = 220, bh = hasIcons ? 130 : 96;
    const GAP = hasLabels ? 120 : 70;
    if (d.layout === "cycle") {
      const cx = W / 2, cy = 235, r = n <= 3 ? 150 : 175;
      bw = 210; bh = hasIcons ? 104 : 80;
      for (let i = 0; i < n; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / n; pos.push([cx + r * 1.6 * Math.cos(a), cy + r * Math.sin(a)]); }
    } else if (d.layout === "hub") {
      // labelled illustration: item 0 is the whole (centre), the others are its labelled parts
      bw = 240; bh = hasIcons ? 104 : 80;
      pos.push([W / 2, 235]);
      const m = n - 1;
      for (let i = 0; i < m; i++) {
        const a = -Math.PI / 2 + Math.PI / Math.max(1, m) + i * 2 * Math.PI / m;
        pos.push([W / 2 + 440 * Math.cos(a), 235 + 168 * Math.sin(a)]);
      }
    } else if (d.layout === "stack") {
      bw = 680; bh = Math.min(84, 400 / n - 10);
      for (let i = 0; i < n; i++) pos.push([W / 2, 40 + bh / 2 + i * (bh + 12)]);
    } else {
      // flow: one row if it fits, else two rows (zig-zag)
      const perRow = n <= 4 ? n : Math.ceil(n / 2);
      bw = Math.min(250, (W - 100 - (perRow - 1) * GAP) / perRow);
      for (let i = 0; i < n; i++) {
        const row = Math.floor(i / perRow), col = i % perRow;
        const rows = Math.ceil(n / perRow);
        const totalW = perRow * bw + (perRow - 1) * GAP;
        const x0 = (W - totalW) / 2 + bw / 2;
        const c = row % 2 === 0 ? col : perRow - 1 - col;
        pos.push([x0 + c * (bw + GAP), rows === 1 ? 235 : 120 + row * 225]);
      }
    }
    // reveal times: when the narration first focuses an item, else staggered at scene start
    const reveal = d.items.map((_, k) => focusTime(sc.beats, k) ?? (sc.start + 0.5 + k * 0.5));

    const edges = [];
    const links = d.layout === "stack" ? [] : d.layout === "hub" ? d.items.slice(1).map((_, k) => [0, k + 1])
      : d.items.map((_, k) => [k, k + 1]).filter(([a, b]) => b < n || d.layout === "cycle").map(([a, b]) => [a, b % n]);
    for (const [a, b] of links) {
      const [x1, y1] = pos[a], [x2, y2] = pos[b];
      const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
      // shorten to box edges
      const sx = Math.abs(dx) / (bw / 2 + 8), sy = Math.abs(dy) / (bh / 2 + 8);
      const cut = len / Math.max(sx, sy, 1e-6);
      const ux = dx / len, uy = dy / len;
      const p = el("svg:path", d.layout === "hub" ? { class: "edge spoke" } : { class: "edge", "marker-end": `url(#ah${sc.index})` }, svg);
      const L = Math.max(1, len - 2 * cut);
      const e = { p, L, b, sx: x1 + ux * cut, sy: y1 + uy * cut, ux, uy, lab: null };
      const txt = hasLabels ? elabels[a] : null;
      if (txt) {
        // label beside the arrow's middle: above it for flow, outside the ring for a cycle
        let nx = uy, ny = -ux;                                   // a normal to the arrow
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
        if (d.layout === "cycle") { if (nx * (mx - W / 2) + ny * (my - 235) < 0) { nx = -nx; ny = -ny; } }
        else if (ny > 0 || (Math.abs(ny) < 0.01 && nx < 0)) { nx = -nx; ny = -ny; }
        const lw = d.layout === "cycle" ? 190 : GAP + 40, lh = 64, off = Math.abs(uy) > 0.7 ? 100 : 40;
        const fo = el("svg:foreignObject", { x: mx + nx * off - lw / 2, y: my + ny * off - lh / 2, width: lw, height: lh });
        const lab = el("div", { class: "edge-label" }, fo);
        el("span", { text: txt }, lab);
        e.lab = fo;  // added after the boxes (below) so a label is never hidden behind a box
      }
      edges.push(e);
    }
    const nodes = d.items.map((txt, k) => {
      const g = el("svg:g", { class: "node" + (d.layout === "hub" && k === 0 ? " centre" : "") }, svg);
      const [x, y] = pos[k];
      el("svg:rect", { x: x - bw / 2, y: y - bh / 2, width: bw, height: bh, rx: 16 }, g);
      el("svg:circle", { cx: x - bw / 2 + 4, cy: y - bh / 2 + 4, r: 17, class: "badge" }, g);
      el("svg:text", { x: x - bw / 2 + 4, y: y - bh / 2 + 10, class: "badge-t", "text-anchor": "middle", text: k + 1 }, g);
      const fo = el("svg:foreignObject", { x: x - bw / 2 + 10, y: y - bh / 2, width: bw - 20, height: bh }, g);
      const div = el("div", { class: "node-label" + (d.layout === "stack" ? " row" : "") }, fo);
      if (icons[k]) el("span", { class: "node-icon", text: icons[k] }, div);
      el("span", { class: "node-text", text: txt }, div);
      div.style.height = bh + "px";
      return { g, x, y };
    });
    edges.forEach(e => { if (e.lab) svg.appendChild(e.lab); });
    return t => {
      const bi = activeBeat(sc.beats, t);
      const cur = bi >= 0 ? sc.beats[bi].focus : null;
      nodes.forEach((nd, k) => {
        const a = ease((t - reveal[k]) / 0.4);
        nd.g.style.opacity = a;
        nd.g.style.transform = `translate(${nd.x}px,${nd.y}px) scale(${0.85 + 0.15 * a}) translate(${-nd.x}px,${-nd.y}px)`;
        nd.g.classList.toggle("active", cur === k);
        nd.g.classList.toggle("done", cur !== null && reveal[k] < reveal[cur] && cur !== k);
      });
      edges.forEach(e => {
        const k = e.b === 0 ? ease((t - reveal[n - 1] - 0.4) / 0.4) : ease((t - reveal[e.b] + 0.35) / 0.35);
        // the line grows from its start; the arrow head rides on its tip
        const l = Math.max(0.5, e.L * k);
        e.p.setAttribute("d", `M${e.sx},${e.sy} L${e.sx + e.ux * l},${e.sy + e.uy * l}`);
        e.p.style.opacity = k > 0.05 ? 1 : 0;
        if (e.lab) e.lab.style.opacity = ease((k - 0.6) / 0.4);
      });
    };
  },

  illustration(root, sc) {
    // main drawing in the centre; inputs on the left flow in, outputs on the right flow out,
    // labelled parts point at it. Each part appears when the narration reaches it.
    const d = sc.data, parts = d.parts;
    const svg = el("svg:svg", { viewBox: `0 0 ${W} 470`, class: "illus" }, root);
    const defs = el("svg:defs", {}, svg);
    const mk = el("svg:marker", { id: `ih${sc.index}`, viewBox: "0 0 10 10", refX: "8", refY: "5", markerWidth: "5", markerHeight: "5", orient: "auto-start-reverse" }, defs);
    el("svg:path", { d: "M0,0 L10,5 L0,10 z", class: "ill-head" }, mk);
    let m = parts.findIndex(p => p.role === "main");
    if (m < 0) m = 0;
    const C = [640, 215], MAIN_R = 112, SAT_R = 52;
    const SL = { TL: [300, 118], L: [190, 262], BL: [300, 392], TR: [980, 118], R: [1090, 262], BR: [980, 392] };
    const free = new Set(Object.keys(SL));
    const take = list => { const s = list.find(k => free.has(k)) || [...free][0]; free.delete(s); return s; };
    const place = parts.map((p, k) => {
      if (k === m) return null;
      const side = p.role === "out" ? "R" : p.role === "in" ? "L" : null;
      const pref = ART_TOP.has(p.art) ? "T" : ART_LOW.has(p.art) ? "B" : "";
      const order = s => [pref + s, s, "T" + s, "B" + s].filter(x => SL[x]);
      return take(side ? order(side) : [...order(k % 2 ? "L" : "R"), ...order(k % 2 ? "R" : "L")]);
    });
    const reveal = parts.map((_, k) => focusTime(sc.beats, k) ?? (sc.start + 0.4 + k * 0.6));
    reveal[m] = Math.min(reveal[m], sc.start + 0.3);
    // arrows and leader lines (drawn first, under the drawings)
    const links = parts.map((p, k) => {
      if (k === m) return null;
      const [sx, sy] = SL[place[k]];
      let [ax, ay, bx, by] = p.role === "out" ? [C[0], C[1], sx, sy] : [sx, sy, C[0], C[1]];
      const dx = bx - ax, dy = by - ay, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len;
      const r0 = p.role === "out" ? MAIN_R : SAT_R + 6, r1 = p.role === "out" ? SAT_R + 14 : MAIN_R + 6;
      ax += ux * r0; ay += uy * r0; bx -= ux * r1; by -= uy * r1;
      const bend = (sy < C[1] ? -1 : 1) * 26;                // curve away from the middle
      const cx = (ax + bx) / 2 + uy * bend * (ux < 0 ? -1 : 1), cy = (ay + by) / 2 - Math.abs(ux) * bend;
      const path = `M${ax},${ay} Q${cx},${cy} ${bx},${by}`;
      const arrow = p.role === "in" || p.role === "out";
      const e = el("svg:path", { d: path, class: "ill-link" + (arrow ? "" : " leader"), ...(arrow ? { "marker-end": `url(#ih${sc.index})` } : {}) }, svg);
      const L = e.getTotalLength ? e.getTotalLength() || len : len;
      e.style.strokeDasharray = arrow ? `${L}` : "7 8";
      const dots = arrow ? [0, 1, 2].map(() => el("svg:circle", { r: 6, class: "ill-dot", fill: ART_TINT[p.art] || "#2F6FED" }, svg)) : [];
      let lab = null;
      if (p.via) {
        // on the curve itself (not its bend point), a little nearer the small drawing
        const u = p.role === "out" ? 0.55 : 0.45, v = 1 - u;
        const mx = v * v * ax + 2 * v * u * cx + u * u * bx, my = v * v * ay + 2 * v * u * cy + u * u * by;
        const fo = el("svg:foreignObject", { x: mx - 100, y: my - 22, width: 200, height: 44 });
        el("span", { text: p.via }, el("div", { class: "ill-via" }, fo));
        lab = fo;
      }
      return { e, L, arrow, dots, lab, q: [ax, ay, cx, cy, bx, by] };
    });
    // drawings and labels
    const nodes = parts.map((p, k) => {
      const [x, y] = k === m ? C : SL[place[k]];
      const s = k === m ? 2.05 : 0.92;
      const grp = el("svg:g", { class: "ill-node" + (k === m ? " main" : "") }, svg);
      el("svg:circle", { cx: x, cy: y, r: k === m ? MAIN_R : SAT_R, class: "ill-halo" }, grp);
      const art = el("svg:g", { transform: `translate(${x},${y}) scale(${s})` }, grp);
      art.innerHTML = ART[p.art] || ART.dot;
      // names of the top pictures go above them, so arrow labels never cover them
      const above = k !== m && place[k].startsWith("T");
      const lw = k === m ? 300 : 230, lh = 64;
      const ly = above ? y - SAT_R - lh - 2 : y + (k === m ? MAIN_R - 6 : SAT_R - 2);
      const fo = el("svg:foreignObject", { x: x - lw / 2, y: ly, width: lw, height: lh }, grp);
      el("span", { text: p.label }, el("div", { class: "ill-label" + (above ? " above" : "") }, fo));
      return { grp, x, y };
    });
    links.forEach(l => { if (l && l.lab) svg.appendChild(l.lab); });
    const at = (q, u) => {   // point on the quadratic curve
      const [ax, ay, cx, cy, bx, by] = q, v = 1 - u;
      return [v * v * ax + 2 * v * u * cx + u * u * bx, v * v * ay + 2 * v * u * cy + u * u * by];
    };
    return t => {
      const bi = activeBeat(sc.beats, t);
      const cur = bi >= 0 ? sc.beats[bi].focus : null;
      nodes.forEach((nd, k) => {
        const a = ease((t - reveal[k]) / 0.45);
        nd.grp.style.opacity = a;
        const pulse = cur === k && t - reveal[k] > 0.45 ? 1 + 0.04 * Math.sin((idle(t) - reveal[k]) * 5) : 1;
        nd.grp.style.transform = `translate(${nd.x}px,${nd.y}px) scale(${(0.8 + 0.2 * a) * pulse}) translate(${-nd.x}px,${-nd.y}px)`;
        nd.grp.classList.toggle("active", cur === k);
      });
      links.forEach((l, k) => {
        if (!l) return;
        const grow = ease((t - reveal[k] - 0.25) / 0.6);
        l.e.style.strokeDashoffset = l.arrow ? `${l.L * (1 - grow)}` : "0";
        l.e.style.opacity = grow > 0.02 ? 1 : 0;
        if (l.arrow) l.e.setAttribute("marker-end", grow > 0.97 ? `url(#ih${sc.index})` : "none");
        l.e.classList.toggle("active", cur === k);
        if (l.lab) l.lab.style.opacity = ease((grow - 0.5) / 0.5);
        // little particles flowing along the arrow once it is drawn (a pure function of t)
        l.dots.forEach((dt, j) => {
          const u = ((idle(t) - reveal[k]) * 0.45 + j / 3) % 1;
          const [px, py] = at(l.q, Math.max(0, u));
          dt.setAttribute("cx", px); dt.setAttribute("cy", py);
          dt.style.opacity = grow >= 1 && t > reveal[k] ? (cur === k ? 0.95 : 0.55) * Math.sin(Math.PI * u) : 0;
        });
      });
    };
  },

  shape(root, sc) {
    // an exact figure; each named part is drawn (lines grow, arcs sweep, areas fill) when the voice reaches it
    const d = sc.data, parts = d.parts;
    const svg = el("svg:svg", { viewBox: `0 0 ${W} 470`, class: "shape-scene" }, root);
    const P = (x, y) => [x, y];
    const line = (a, b) => `M${a[0]},${a[1]} L${b[0]},${b[1]}`;
    const arcPath = (c, r, a0, a1) => {           // degrees, counter-clockwise on screen (y up)
      const p0 = [c[0] + r * Math.cos(a0 * Math.PI / 180), c[1] - r * Math.sin(a0 * Math.PI / 180)];
      const p1 = [c[0] + r * Math.cos(a1 * Math.PI / 180), c[1] - r * Math.sin(a1 * Math.PI / 180)];
      const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
      return `M${p0[0]},${p0[1]} A${r},${r} 0 ${large} 0 ${p1[0]},${p1[1]}`;
    };
    const mid = (a, b, dx = 0, dy = 0) => [(a[0] + b[0]) / 2 + dx, (a[1] + b[1]) / 2 + dy];
    const poly = pts => "M" + pts.map(p => p.join(",")).join(" L") + " Z";
    const cornerBox = (v, a, b, s = 26) => {      // small right-angle square at v between directions to a and b
      const u = (p) => { const dx = p[0] - v[0], dy = p[1] - v[1], l = Math.hypot(dx, dy); return [dx / l * s, dy / l * s]; };
      const [ax, ay] = u(a), [bx, by] = u(b);
      return `M${v[0] + ax},${v[1] + ay} L${v[0] + ax + bx},${v[1] + ay + by} L${v[0] + bx},${v[1] + by}`;
    };
    // geometry for each shape: outline + one drawable element per part name
    let outline = "", el2 = {};
    const C = P(470, 235);
    if (d.shape === "circle") {
      const r = 175;
      outline = arcPath(C, r, 0, 359.99);
      el2 = {
        centre: { dot: C, at: [C[0] - 80, C[1] - 30] },
        radius: { d: line(C, [C[0] + r * Math.cos(0.7), C[1] - r * Math.sin(0.7)]), at: [C[0] + 80, C[1] - 92] },
        diameter: { d: line([C[0] - r, C[1]], [C[0] + r, C[1]]), at: [C[0] + 60, C[1] + 32] },
        circumference: { d: arcPath(C, r, 0, 359.99), at: [C[0] + r + 30, C[1] + 120], wide: true },
        chord: { d: line([C[0] + r * Math.cos(3.6), C[1] - r * Math.sin(3.6)], [C[0] + r * Math.cos(5.6), C[1] - r * Math.sin(5.6)]), at: [C[0] - 10, C[1] + 150] },
        arc: { d: arcPath(C, r, 100, 160), at: [C[0] - 190, C[1] - 150], wide: true },
        area: { fill: arcPath(C, r, 0, 359.99) + " Z", at: [C[0] - 70, C[1] - 40] },
      };
    } else if (d.shape === "right_triangle") {
      const B = P(300, 405), Cc = P(700, 405), A = P(300, 85);
      outline = poly([A, B, Cc]);
      el2 = {
        base: { d: line(B, Cc), at: mid(B, Cc, 0, 34) }, height: { d: line(B, A), at: mid(B, A, -80, 0) },
        hypotenuse: { d: line(A, Cc), at: mid(A, Cc, 70, -30) }, right_angle: { d: cornerBox(B, A, Cc), at: [B[0] + 50, B[1] - 40] },
        angle: { d: arcPath(Cc, 70, 180 - 38.66, 180), at: [Cc[0] - 140, Cc[1] - 30] }, area: { fill: poly([A, B, Cc]), at: [390, 320] },
      };
    } else if (d.shape === "triangle") {
      const A = P(270, 405), B = P(690, 405), Cc = P(430, 85);
      outline = poly([A, B, Cc]);
      const foot = P(430, 405);
      el2 = {
        side_c: { d: line(A, B), at: mid(A, B, 0, 34) }, base: { d: line(A, B), at: mid(A, B, 0, 34) },
        side_a: { d: line(B, Cc), at: mid(B, Cc, 60, -10) }, side_b: { d: line(Cc, A), at: mid(Cc, A, -70, -10) },
        height: { d: line(Cc, foot), at: mid(Cc, foot, 60, -40), dash: true },
        angle_a: { d: arcPath(A, 60, 0, 63), at: [A[0] + 70, A[1] - 36] }, angle_b: { d: arcPath(B, 60, 117, 180), at: [B[0] - 110, B[1] - 36] },
        angle_c: { d: arcPath(Cc, 56, 243, 297 + 20), at: [Cc[0], Cc[1] + 90] }, area: { fill: poly([A, B, Cc]), at: [560, 350] },
      };
    } else if (d.shape === "square" || d.shape === "rectangle") {
      const sq = d.shape === "square";
      const x0 = sq ? 300 : 220, x1 = sq ? 640 : 720, y0 = sq ? 65 : 105, y1 = sq ? 405 : 385;
      const A = P(x0, y0), B = P(x1, y0), Cc = P(x1, y1), D = P(x0, y1);
      outline = poly([A, B, Cc, D]);
      el2 = {
        side: { d: line(A, B), at: mid(A, B, 0, -26) }, length: { d: line(D, Cc), at: mid(D, Cc, 0, 34) },
        width: { d: line(B, Cc), at: mid(B, Cc, 80, 0) }, diagonal: { d: line(A, Cc), at: mid(A, Cc, 60, -20), dash: true },
        area: { fill: poly([A, B, Cc, D]), at: [(x0 + x1) / 2 - 60, (y0 + y1) / 2 + 60] },
        perimeter: { d: poly([A, B, Cc, D]), at: [x1 + 40, y0 - 10], wide: true },
        right_angle: { d: cornerBox(D, A, Cc), at: [D[0] + 46, D[1] - 36] },
      };
    } else if (d.shape === "polygon") {
      const n = d.sides || 6, r = 175;
      const pts = [...Array(n)].map((_, i) => P(C[0] + r * Math.cos(Math.PI / 2 + i * 2 * Math.PI / n), C[1] - r * Math.sin(Math.PI / 2 + i * 2 * Math.PI / n)));
      outline = poly(pts);
      const v = pts[1], a0 = Math.atan2(-(pts[0][1] - v[1]), pts[0][0] - v[0]) * 180 / Math.PI, a1 = Math.atan2(-(pts[2][1] - v[1]), pts[2][0] - v[0]) * 180 / Math.PI;
      el2 = {
        side: { d: line(pts[0], pts[1]), at: mid(pts[0], pts[1], -40, -30) }, vertex: { dot: pts[1], at: [pts[1][0] - 60, pts[1][1] - 20] },
        angle: { d: arcPath(v, 44, Math.min(a0, a1), Math.max(a0, a1)), at: [v[0] + 70, v[1] + 10] }, centre: { dot: C, at: [C[0] + 20, C[1] + 30] },
        area: { fill: poly(pts), at: [C[0] - 40, C[1] + 70] }, perimeter: { d: poly(pts), at: [C[0] + r + 20, C[1] - 120], wide: true },
      };
    } else {                                           // angle
      const deg = d.degrees || 60, V = P(300, 360), L = 380;
      const E2 = P(V[0] + L * Math.cos(deg * Math.PI / 180), V[1] - L * Math.sin(deg * Math.PI / 180));
      outline = line(V, P(V[0] + L, V[1])) + " " + line(V, E2);
      el2 = {
        arm_1: { d: line(V, P(V[0] + L, V[1])), at: [V[0] + L - 40, V[1] + 34] }, arm_2: { d: line(V, E2), at: mid(V, E2, -60, -10) },
        vertex: { dot: V, at: [V[0] - 70, V[1] + 30] }, angle: { d: arcPath(V, 90, 0, deg), at: [V[0] + 120, V[1] - 50] },
      };
    }
    el("svg:path", { d: outline, class: "sh-outline" }, svg);
    const reveal = parts.map((_, k) => focusTime(sc.beats, k) ?? (sc.start + 0.6 + k * 0.7));
    const items = parts.map((pt, k) => {
      const g = el2[pt.part] || {};
      let node = null, L = 1;
      if (g.fill) node = el("svg:path", { d: g.fill, class: "sh-area" }, svg);
      else if (g.dot) node = el("svg:circle", { cx: g.dot[0], cy: g.dot[1], r: 9, class: "sh-dot" }, svg);
      else if (g.d) {
        node = el("svg:path", { d: g.d, class: "sh-part" + (g.dash ? " dash" : "") + (g.wide ? " wide" : "") }, svg);
        L = node.getTotalLength ? node.getTotalLength() || 400 : 400;
        if (!g.dash) node.style.strokeDasharray = `${L}`;
      }
      const at = g.at || [900, 80 + k * 60];
      const fo = el("svg:foreignObject", { x: at[0] - 130, y: at[1] - 24, width: 260, height: 48 });
      el("span", { text: pt.label }, el("div", { class: "sh-label" }, fo));
      return { node, L, fo, g };
    });
    items.forEach(it => svg.appendChild(it.fo));      // labels on top of every line
    const base = el("svg:path", { d: outline, class: "sh-draw" }, svg);
    const BL = base.getTotalLength ? base.getTotalLength() || 1200 : 1200;
    base.style.strokeDasharray = `${BL}`;
    svg.insertBefore(base, svg.children[1]);
    return t => {
      const lt = t - sc.start;
      base.style.strokeDashoffset = `${BL * (1 - ease(lt / 1.2))}`;      // the figure draws itself first
      const bi = activeBeat(sc.beats, t);
      const cur = bi >= 0 ? sc.beats[bi].focus : null;
      items.forEach((it, k) => {
        const a = ease((t - reveal[k]) / 0.8);
        if (it.node) {
          if (it.g.fill) it.node.style.opacity = 0.55 * a;
          else if (it.g.dot) { it.node.style.opacity = a; it.node.setAttribute("r", 4 + 6 * a); }
          else { it.node.style.opacity = a > 0.01 ? 1 : 0; if (!it.g.dash) it.node.style.strokeDashoffset = `${it.L * (1 - a)}`; }
          it.node.classList.toggle("active", cur === k);
        }
        it.fo.style.opacity = ease((t - reveal[k] - 0.4) / 0.4);
        it.fo.classList.toggle("active", cur === k);
      });
    };
  },

  table(root, sc) {
    // comparison table: the header slides in, each row appears when the voice reaches it, the current row glows
    const d = sc.data;
    const wrap = el("div", { class: "tbl-wrap" }, root);
    const tb = el("table", { class: "tbl" }, wrap);
    const head = el("tr", { class: "tbl-head" }, el("thead", {}, tb));
    d.columns.forEach(c => el("th", { text: c }, head));
    const body = el("tbody", {}, tb);
    const rows = d.rows.map(r => { const tr = el("tr", {}, body); r.forEach((c, i) => el("td", { text: c, class: i === 0 ? "first" : "" }, tr)); return tr; });
    const big = d.rows.length > 4 || d.columns.length > 3;
    tb.classList.toggle("dense", big);
    const reveal = d.rows.map((_, k) => focusTime(sc.beats, k) ?? (sc.start + 0.7 + k * 0.6));
    return t => {
      const lt = t - sc.start;
      const a = ease(lt / 0.5);
      head.style.opacity = a; head.style.transform = `translateY(${(1 - a) * -14}px)`;
      const bi = activeBeat(sc.beats, t);
      const cur = bi >= 0 ? sc.beats[bi].focus : null;
      rows.forEach((tr, k) => {
        const b = ease((t - reveal[k]) / 0.45);
        tr.style.opacity = b; tr.style.transform = `translateX(${(1 - b) * 40}px)`;
        tr.classList.toggle("active", cur === k);
      });
    };
  },

  timeline(root, sc) {
    const d = sc.data, n = d.events.length;
    const wrap = el("div", { class: "tl" }, root);
    const line = el("div", { class: "tl-line" }, wrap);
    const fill = el("div", { class: "tl-fill" }, line);
    const gap = (W - 160) / n;
    const reveal = d.events.map((_, k) => focusTime(sc.beats, k) ?? (sc.start + 0.5 + k * 0.6));
    const evs = d.events.map((e, k) => {
      const x = 80 + gap * (k + 0.5);
      const box = el("div", { class: "tl-ev" }, wrap);
      box.style.left = (x - gap / 2 + 6) + "px"; box.style.width = (gap - 12) + "px";
      el("div", { class: "tl-label", text: e.label }, box);
      el("div", { class: "tl-dot" }, box);
      el("div", { class: "tl-text", text: e.text }, box);
      return { box, x };
    });
    return t => {
      const bi = activeBeat(sc.beats, t);
      const cur = bi >= 0 ? sc.beats[bi].focus : null;
      let reach = 0;
      evs.forEach((e, k) => {
        const a = ease((t - reveal[k]) / 0.4);
        e.box.style.opacity = a;
        e.box.style.transform = `translateY(${(1 - a) * 24}px)`;
        e.box.classList.toggle("active", cur === k);
        if (a > 0) reach = Math.max(reach, e.x - 80);
      });
      fill.style.width = reach + "px";
    };
  },

  chart(root, sc) {
    const d = sc.data, n = d.labels.length;
    const svg = el("svg:svg", { viewBox: `0 0 ${W} 470`, class: "chart" }, root);
    const X0 = 150, X1 = W - 110, Y0 = 380, Y1 = 70;
    if (d.chart_title) el("svg:text", { x: W / 2, y: 32, class: "chart-title", "text-anchor": "middle", text: d.chart_title }, svg);
    el("svg:line", { x1: X0, y1: Y0, x2: X1, y2: Y0, class: "axis" }, svg);
    el("svg:line", { x1: X0, y1: Y0, x2: X0, y2: Y1 - 10, class: "axis" }, svg);
    const max = Math.max(...d.values, 1e-9);
    const slot = (X1 - X0) / n, bwid = Math.min(150, slot * 0.6);
    const num = v => Math.abs(v - Math.round(v)) < 1e-9 ? String(Math.round(v)) : String(+v.toFixed(2));
    const pre = ["pH", "$", "₹", "€", "£"].includes(d.unit);
    const fmt = v => !d.unit ? num(v) : pre ? (d.unit === "pH" ? "pH " : d.unit) + num(v) : num(v) + (d.unit === "%" ? "%" : " " + d.unit);
    for (let g = 1; g <= 4; g++) {
      const y = Y0 - (Y0 - Y1) * g / 4;
      el("svg:line", { x1: X0, y1: y, x2: X1, y2: y, class: "grid" }, svg);
      el("svg:text", { x: X0 - 12, y: y + 6, class: "tick-t", "text-anchor": "end", text: num(max * g / 4) }, svg);
    }
    const reveal = d.labels.map((_, k) => focusTime(sc.beats, k) ?? (sc.start + 0.5 + k * 0.4));
    const bars = d.values.map((v, k) => {
      const cx = X0 + slot * (k + 0.5);
      const h = Math.max(4, (Y0 - Y1) * v / max);
      const r = el("svg:rect", { x: cx - bwid / 2, y: Y0 - h, width: bwid, height: h, rx: 8, class: "bar" }, svg);
      const val = el("svg:text", { x: cx, y: Y0 - h - 12, class: "bar-v", "text-anchor": "middle", text: fmt(v) }, svg);
      const fo = el("svg:foreignObject", { x: cx - slot / 2, y: Y0 + 8, width: slot, height: 70 }, svg);
      el("div", { class: "bar-l", text: d.labels[k] }, fo);
      return { r, val, h, fo };
    });
    return t => {
      const bi = activeBeat(sc.beats, t);
      const cur = bi >= 0 ? sc.beats[bi].focus : null;
      bars.forEach((b, k) => {
        const a = ease((t - reveal[k] + 0.2) / 0.6);
        b.r.style.transform = `scaleY(${Math.max(0.001, a)})`;
        b.r.style.transformOrigin = `0 ${Y0}px`;
        b.val.style.opacity = ease((a - 0.7) / 0.3);
        b.fo.style.opacity = Math.min(1, a * 3);
        b.r.classList.toggle("active", cur === k);
      });
    };
  },

  worked_example(root, sc) {
    const d = sc.data, n = d.steps.length;
    const wrap = el("div", { class: "we" }, root);
    const prob = el("div", { class: "we-prob" }, wrap);
    el("span", { class: "we-tag", text: "Problem" }, prob);
    el("span", { text: d.problem }, prob);
    const list = el("div", { class: "we-steps" }, wrap);
    const rows = d.steps.map((st, k) => {
      const r = el("div", { class: "we-step" }, list);
      el("span", { class: "we-n", text: k + 1 }, r);
      el("span", { class: "we-t", text: st }, r);
      return r;
    });
    const ans = el("div", { class: "we-ans" }, wrap);
    el("span", { class: "we-tag ok", text: "Answer" }, ans);
    el("span", { text: d.answer }, ans);
    const reveal = d.steps.map((_, k) => focusTime(sc.beats, k) ?? (sc.start + 0.8 + k * 1.2));
    for (let k = 1; k < n; k++) reveal[k] = Math.max(reveal[k], reveal[k - 1] + 0.2);
    const ansAt = Math.max(reveal[n - 1] + 1.0, (sc.beats.at(-1)?.start ?? 0));
    return t => {
      const lt = t - sc.start;
      prob.style.opacity = ease(lt / 0.5);
      const bi = activeBeat(sc.beats, t);
      const cur = bi >= 0 ? sc.beats[bi].focus : null;
      rows.forEach((r, k) => {
        const a = ease((t - reveal[k]) / 0.35);
        r.style.opacity = a; r.style.transform = `translateX(${(1 - a) * -24}px)`;
        r.classList.toggle("active", cur === k);
      });
      const a = ease((t - ansAt) / 0.4);
      ans.style.opacity = a; ans.style.transform = `scale(${0.9 + 0.1 * a})`;
    };
  },

  quiz(root, sc) {
    const d = sc.data;
    const wrap = el("div", { class: "quiz" }, root);
    const q = el("div", { class: "quiz-q", text: d.question }, wrap);
    const opts = d.options.map((o, i) => {
      const r = el("div", { class: "quiz-o" }, wrap);
      el("span", { class: "quiz-l", text: String.fromCharCode(65 + i) }, r);
      el("span", { text: o }, r);
      return r;
    });
    const revealAt = focusTime(sc.beats, d.answer) ?? (sc.beats.at(-1)?.start ?? sc.end - 1);
    return t => {
      const lt = t - sc.start;
      q.style.opacity = ease(lt / 0.5);
      opts.forEach((o, i) => { const a = ease((lt - 0.4 - i * 0.2) / 0.35); o.style.opacity = a; o.style.transform = `translateX(${(1 - a) * 30}px)`; });
      const shown = t >= revealAt;
      opts.forEach((o, i) => { o.classList.toggle("right", shown && i === d.answer); o.classList.toggle("wrong", shown && i !== d.answer); });
    };
  },
};

// player shell ---------------------------------------------------------------
export class Player {
  constructor(stage, tl, base) {
    this.tl = tl; this.base = base; this.stage = stage;
    stage.innerHTML = "";
    stage.style.setProperty("--script-font", `"${tl.font}"`);
    stage.lang = tl.language;
    const top = el("div", { class: "topbar" }, stage);
    this.stepEl = el("div", { class: "step" }, top);
    el("div", { class: "lesson-title", text: tl.title }, top);
    this.sceneRoot = el("div", { class: "scene-root" }, stage);
    this.capEl = el("div", { class: "caption" }, stage);
    this.pb = el("div", { class: "progress" }, stage);
    this.fill = el("div", { class: "fill" }, this.pb);
    this.titleEl = top.lastChild;
    this.wait = el("div", { class: "wait" }, stage);
    el("span", { class: "wait-dot" }, this.wait);
    el("span", { text: "Writing the next scene…" }, this.wait);
    this.cur = -1; this.update = null;
    this.setTimeline(tl);
  }
  setTimeline(tl) {
    // called again while the lesson is still being written: more scenes, longer duration
    this.tl = tl;
    this.titleEl.textContent = tl.title;
    this.pb.querySelectorAll(".tick").forEach(t => t.remove());
    tl.scenes.forEach(s => { const k = el("div", { class: "tick" }, this.pb); k.style.left = (100 * s.start / tl.duration) + "%"; });
  }
  setWaiting(on) { this.wait.style.opacity = on ? 1 : 0; }
  sceneAt(t) {
    const s = this.tl.scenes;
    for (let i = s.length - 1; i >= 0; i--) if (t >= s[i].start) return i;
    return 0;
  }
  render(t) {
    t = clamp(t, 0, this.tl.duration);
    const i = this.sceneAt(t), sc = this.tl.scenes[i];
    if (i !== this.cur) {
      this.cur = i; this.sceneRoot.innerHTML = "";
      const host = el("div", { class: `scene scene-${sc.type}` }, this.sceneRoot);
      this.update = (Scenes[sc.type] || Scenes.title_card)(host, sc);
      this.stepEl.textContent = sc.data.heading;
      this.stepEl.style.display = sc.type === "title_card" ? "none" : "";
    }
    this.update(t);
    // fade scenes in/out
    const fin = ease((t - sc.start) / 0.3), fout = ease((sc.end - t) / 0.3);
    this.sceneRoot.style.opacity = Math.min(fin, i === this.tl.scenes.length - 1 ? 1 : fout);
    // caption: current beat (stays until next beat begins)
    const bi = activeBeat(sc.beats, t);
    const txt = bi >= 0 ? sc.beats[bi].text : "";
    if (this.capEl.textContent !== txt) this.capEl.textContent = txt;
    this.capEl.style.opacity = txt ? 1 : 0;
    this.fill.style.width = (100 * t / this.tl.duration) + "%";
  }
}
