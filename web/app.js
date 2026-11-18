// NameDedup website. Vanilla JS, no build step. The API lives at /api/* (web_api.py).
//
// Safety: every piece of text from the API or the user reaches the page through
// textContent (see h() below). Nothing is ever assigned to innerHTML, so a name such as
// "<img onerror=...>" is shown as plain text and never parsed as markup.
"use strict";

// ------------------------------------------------------------------ helpers
/** h("td", {class: "num"}, "0.500", child) -> element. Strings become text nodes. */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const $ = (sel) => document.querySelector(sel);
const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const API_DOWN = "Could not reach the API. Start it with: python -m uvicorn web_api:app --reload";

/** GET JSON; throws Error(message) with the API's own "detail" when there is one. */
async function getJSON(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  let res;
  try {
    res = await fetch(url, { headers: { Accept: "application/json" } });
  } catch {
    throw new Error(API_DOWN);
  }
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const detail = body && typeof body.detail === "string" ? body.detail
      : `Request failed (HTTP ${res.status}).`;
    throw new Error(detail);
  }
  return body;
}

/** Replace a region's content and keep aria-busy in sync. */
function show(region, busy, ...nodes) {
  region.setAttribute("aria-busy", String(busy));
  region.replaceChildren(...nodes);
}
const stateMsg = (kind, text) => h("p", { class: `state state-${kind}` }, text);

/** Latest-call-wins guard: stale responses from earlier clicks are ignored. */
function latest() {
  let n = 0;
  return () => { const id = ++n; return () => id === n; };
}

const VERDICT_CLASS = { "Likely duplicate": "likely", "Needs review": "review",
                        "Different person": "diff" };
const badge = (verdict) => h("span", { class: `badge badge-${VERDICT_CLASS[verdict] || "diff"}` }, verdict);

/** 'hybrid_50_30_20' -> 'Hybrid 0.50/0.30/0.20'; 'dmetaphone' -> 'Double Metaphone'. */
function methodLabel(m) {
  const names = { exact: "Exact", trigram: "Trigram", levenshtein: "Levenshtein",
                  dmetaphone: "Double Metaphone", soundex: "Soundex" };
  if (m.startsWith("hybrid_")) {
    return "Hybrid " + m.split("_").slice(1).map((p) => (Number(p) / 100).toFixed(2)).join("/");
  }
  return names[m] || m;
}

/** Empty-name check for a text field; shows/hides its error message. */
function requireName(input, errorEl) {
  const value = input.value.trim();
  input.setAttribute("aria-invalid", String(!value));
  if (errorEl) errorEl.hidden = Boolean(value);
  if (!value) input.focus();
  return value;
}

// --------------------------------------------------------------- mobile menu
const toggle = $(".nav-toggle");
const links = $("#nav-links");
toggle.addEventListener("click", () => {
  const open = toggle.getAttribute("aria-expanded") === "true";
  toggle.setAttribute("aria-expanded", String(!open));
  links.classList.toggle("open", !open);
});
links.addEventListener("click", (e) => {
  if (e.target.closest("a")) {
    toggle.setAttribute("aria-expanded", "false");
    links.classList.remove("open");
  }
});

// ------------------------------------------------- highlight current section
const navLinks = [...links.querySelectorAll("a")];
const observer = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    for (const a of navLinks) {
      if (a.getAttribute("href") === `#${entry.target.id}`) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    }
  }
}, { rootMargin: "-45% 0px -50% 0px" });
navLinks.forEach((a) => { const s = $(a.getAttribute("href")); if (s) observer.observe(s); });

// ================================================================== Home
async function loadStats() {
  const region = $("#stats");
  const set = (key, text) => { $(`[data-stat="${key}"]`).textContent = text; };
  try {
    const s = await getJSON("/api/stats");
    set("records", s.records.toLocaleString("en"));
    set("pairs", s.gold_pairs.toLocaleString("en"));
    if (s.best_method) {
      set("f1", s.best_method.f1.toFixed(3));
      set("f1-sub", methodLabel(s.best_method.method));
    } else {
      set("f1", "–");
      set("f1-sub", "run python src/evaluate.py");
    }
    if (s.speedup) {
      const [method, x] = Object.entries(s.speedup.by_method).sort((a, b) => b[1] - a[1])[0];
      set("speedup", `${x.toFixed(1)}×`);
      set("speedup-sub", `${methodLabel(method)}, ${(s.speedup.n_records / 1000).toFixed(0)}k records`);
    } else {
      set("speedup", "–");
      set("speedup-sub", "run python src/benchmark.py");
    }
  } catch (err) {
    for (const key of ["records", "pairs", "f1", "speedup"]) set(key, "–");
    const box = $("#stats-error");
    box.textContent = `Statistics unavailable: ${err.message}`;
    box.hidden = false;
  } finally {
    region.setAttribute("aria-busy", "false");
  }
}
loadStats();

// ================================================================ Try it
const form = $("#search-form");
const nameInput = $("#name");
const methodSelect = $("#method");
const normalizeSwitch = $("#normalize");
const normalizeHint = $("#normalize-hint");
const searchButton = $("#search-button");
const searchOutput = $("#search-output");
const ALWAYS_NORMALIZED = new Set(["Custom normalization", "Hybrid"]);
let userNormalize = normalizeSwitch.checked;   // the user's choice for raw-name methods

function syncNormalizeSwitch() {
  const fixed = ALWAYS_NORMALIZED.has(methodSelect.value);
  normalizeSwitch.disabled = fixed;
  normalizeSwitch.checked = fixed ? true : userNormalize;
  normalizeHint.textContent = fixed ? "Always on for this method."
    : "Compare normalized names instead of raw spellings.";
}
normalizeSwitch.addEventListener("change", () => { userNormalize = normalizeSwitch.checked; });
methodSelect.addEventListener("change", () => {
  syncNormalizeSwitch();
  if (searchOutput.dataset.hasResults) runSearch();   // re-run with the new method
});
syncNormalizeSwitch();

/** Name cell: words that match the query (after normalization) in bold. */
function nameCell(match) {
  const parts = match.name_parts || [{ text: match.full_name, match: false }];
  return h("td", { class: "name-cell" },
    parts.map((p) => (p.match ? h("strong", {}, p.text) : h("span", { class: "rest" }, p.text))));
}

function scoreCell(score) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  return h("td", { class: "num" },
    h("div", { class: "score" },
      h("span", {}, score.toFixed(3)),
      h("span", { class: "score-bar", "aria-hidden": "true" },
        h("span", { style: `width:${pct.toFixed(1)}%` }))));
}

function summaryCard(label, value, mono = false) {
  return h("div", { class: "card" },
    h("div", { class: "label" }, label),
    h("div", { class: mono ? "value mono" : "value" }, value));
}

function renderSearch(d) {
  const summary = h("div", { class: "summary" },
    summaryCard("Normalized as", d.normalized || "–", true),
    summaryCard("Method", d.method + (d.normalize && !ALWAYS_NORMALIZED.has(d.method) ? " (normalized)" : "")),
    summaryCard("Query time", `${d.elapsed_ms.toFixed(1)} ms`));

  if (!d.matches.length) {
    return [summary, stateMsg("empty", "No similar names found above this threshold.")];
  }
  const table = h("table", { class: "table" },
    h("caption", {}, `Top ${d.matches.length} records scoring at least ${d.threshold.toFixed(2)}. `
      + "Bold words match the search after normalization."),
    h("thead", {}, h("tr", {},
      h("th", { scope: "col", class: "num" }, "Record"),
      h("th", { scope: "col" }, "Name in database"),
      h("th", { scope: "col" }, "Normalized"),
      h("th", { scope: "col", class: "num" }, "Score"),
      h("th", { scope: "col" }, "Verdict"))),
    h("tbody", {}, d.matches.map((m) => h("tr", {},
      h("td", { class: "num" }, m.record_id),
      nameCell(m),
      h("td", { class: "mono" }, m.normalized_name || "–"),
      scoreCell(m.score),
      h("td", {}, badge(m.verdict))))));
  return [summary, h("div", { class: "table-wrap" }, table)];
}

const searchGuard = latest();
async function runSearch() {
  const name = requireName(nameInput, $("#name-error"));
  if (!name) return;
  const isCurrent = searchGuard();
  searchButton.disabled = true;
  searchButton.textContent = "Searching…";
  show(searchOutput, true, stateMsg("loading", `Searching for “${name}”…`));
  try {
    const d = await getJSON("/api/search", {
      name, method: methodSelect.value, normalize: normalizeSwitch.checked,
    });
    if (!isCurrent()) return;
    show(searchOutput, false, ...renderSearch(d));
    searchOutput.dataset.hasResults = "1";
  } catch (err) {
    if (!isCurrent()) return;
    show(searchOutput, false, stateMsg("error", err.message));
  } finally {
    if (isCurrent()) {
      searchButton.disabled = false;
      searchButton.textContent = "Search";
    }
  }
}

form.addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });
nameInput.addEventListener("input", () => {
  if (nameInput.value.trim()) { nameInput.setAttribute("aria-invalid", "false"); $("#name-error").hidden = true; }
});
for (const chip of document.querySelectorAll("[data-example]")) {
  chip.addEventListener("click", () => { nameInput.value = chip.dataset.example; runSearch(); });
}

// =========================================================== How it works
// ------------------------------------------------------ Watch normalization
const stepsOutput = $("#steps-output");
const stepsGuard = latest();
let stepsTimers = [];

function stepRow(s) {
  return h("tr", {},
    h("td", {}, h("span", { class: "mono" }, s.rule), h("span", { class: "rule-group" }, s.rule_group)),
    h("td", { class: "mono" }, s.before),
    h("td", { class: "arrow-cell", "aria-hidden": "true" }, "→"),
    h("td", { class: "mono" }, s.after));
}

async function runSteps(e) {
  e?.preventDefault();
  const input = $("#steps-name");
  const name = requireName(input);
  if (!name) return;
  const isCurrent = stepsGuard();
  stepsTimers.forEach(clearTimeout);
  stepsTimers = [];
  show(stepsOutput, true, stateMsg("loading", "Normalizing…"));
  let d;
  try {
    d = await getJSON("/api/normalize-steps", { name });
  } catch (err) {
    if (isCurrent()) show(stepsOutput, false, stateMsg("error", err.message));
    return;
  }
  if (!isCurrent()) return;
  if (!d.steps.length) {
    show(stepsOutput, false, stateMsg("empty", "No rule changes this name; it is already normalized."));
    return;
  }
  const tbody = h("tbody");
  const result = h("p", { class: "result-line", hidden: true },
    "Result: ", h("code", {}, d.normalized), ` after ${d.steps.length} changes.`);
  show(stepsOutput, true,
    h("div", { class: "table-wrap" }, h("table", { class: "table steps-table" },
      h("caption", {}, "Rules that changed the name, in the order they ran."),
      h("thead", {}, h("tr", {},
        h("th", { scope: "col" }, "Rule"), h("th", { scope: "col" }, "Before"),
        h("td", { "aria-hidden": "true" }), h("th", { scope: "col" }, "After"))),
      tbody)),
    result);

  const delay = prefersReducedMotion() ? 0 : 450;   // rows appear one by one
  d.steps.forEach((s, i) => {
    stepsTimers.push(setTimeout(() => {
      if (!isCurrent()) return;
      tbody.append(stepRow(s));
      if (i === d.steps.length - 1) { result.hidden = false; stepsOutput.setAttribute("aria-busy", "false"); }
    }, delay * i));
  });
}
$("#steps-form").addEventListener("submit", runSteps);

// --------------------------------------------------- Compare all methods
const compareOutput = $("#compare-output");
const compareGuard = latest();

function renderCompare(d) {
  if (!d.candidates.length) {
    return [stateMsg("empty", "No method found a similar name above 0.30.")];
  }
  const methods = d.method_names;
  const table = h("table", { class: "table compare-table" },
    h("caption", {}, `Every record that any method ranked in its top 5 for “${d.name}”, `
      + "scored by all six methods."),
    h("thead", {}, h("tr", {},
      h("th", { scope: "col" }, "Name in database"),
      methods.map((m) => h("th", { scope: "col", class: "method" }, m)))),
    h("tbody", {}, d.candidates.map((c) => h("tr", {},
      h("th", { scope: "row", class: "name-cell" }, c.full_name),
      methods.map((m) => {
        const v = c.verdicts[m];
        return h("td", { class: `cell cell-${VERDICT_CLASS[v] || "diff"}`, title: v },
          c.scores[m].toFixed(3), h("span", { class: "visually-hidden" }, `, ${v}`));
      })))));
  return [h("div", { class: "table-wrap" }, table)];
}

async function runCompare(e) {
  e?.preventDefault();
  const input = $("#compare-name");
  const name = requireName(input);
  if (!name) return;
  const isCurrent = compareGuard();
  show(compareOutput, true, stateMsg("loading", "Scoring with all six methods…"));
  try {
    const d = await getJSON("/api/compare", { name });
    if (isCurrent()) show(compareOutput, false, ...renderCompare(d));
  } catch (err) {
    if (isCurrent()) show(compareOutput, false, stateMsg("error", err.message));
  }
}
$("#compare-form").addEventListener("submit", runCompare);

// ================================================================ Results
// Charts drawn with Chart.js from web/vendor/ (works offline). Colours: design-system
// primary for the best bar, --border-strong grey for the rest; the source series reuse
// the CATEGORICAL order from src/plots.py so the PNG figures and the page match.
const SOURCES = [["hard_negative", "Hard negative"], ["trigram", "Trigram-similar"],
                 ["levenshtein", "Levenshtein-similar"], ["dmetaphone", "Same Double Metaphone code"]];
const SOURCE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"];

async function loadResults() {
  const fail = (msg) => {
    $("#f1-takeaway").textContent = "Results unavailable.";
    const box = $("#results-error"); box.textContent = msg; box.hidden = false;
  };
  if (!window.Chart) return fail("Chart.js did not load (web/vendor/chart.umd.min.js missing).");
  let d;
  try { d = await getJSON("/api/metrics"); } catch (err) { return fail(err.message); }

  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.color = "#4B5563";
  Chart.defaults.borderColor = "#E3E5E8";

  // one bar per method: its best (method, normalized) row; d.best is sorted by F1
  const best = [];
  for (const r of d.best) if (!best.some((b) => b.method === r.method)) best.push(r);
  const top = best[0];
  const second = best.find((r) => !r.method.startsWith("hybrid_")) || best[1];
  $("#f1-takeaway").textContent = `${methodLabel(top.method)} on ${top.normalized ? "normalized" : "raw"} `
    + `names scores the highest F1, ${top.f1.toFixed(3)}, ahead of the best single method, ${methodLabel(second.method)}, `
    + `at ${second.f1.toFixed(3)}.`;
  const axisTitle = (text) => ({ display: true, text, color: "#4B5563", font: { weight: 600 },
                                 padding: { top: 8, bottom: 8 } });

  new Chart($("#f1-chart"), {
    type: "bar",
    data: {
      labels: best.map((r) => methodLabel(r.method)),
      datasets: [{ data: best.map((r) => r.f1), borderRadius: 4, barPercentage: 0.7,
                   backgroundColor: best.map((_, i) => (i === 0 ? "#1D4ED8" : "#8A919C")) }],
    },
    options: {
      indexAxis: "y", maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => {
          const r = best[c.dataIndex];
          return [`F1 ${r.f1.toFixed(3)} (${r.normalized ? "normalized" : "raw"} names, threshold ${r.threshold.toFixed(2)})`,
                  `Precision ${(r.precision * 100).toFixed(1)}%, recall ${(r.recall * 100).toFixed(1)}%`];
        } } },
      },
      scales: {
        x: { min: 0, max: 1, title: axisTitle("F1 score (0 to 1, higher is better)") },
        y: { grid: { display: false }, title: axisTitle("Method") },
      },
    },
  });

  // grouped bars: x = method, one series per non-duplicate pair source
  const fpMethods = best.filter((r) => r.method !== "exact");
  const rate = (m, s) => {
    const row = d.by_source.find((x) => x.method === m.method && x.normalized === m.normalized && x.source === s);
    return row ? row.rate * 100 : 0;
  };
  new Chart($("#fp-chart"), {
    type: "bar",
    data: {
      labels: fpMethods.map((r) => methodLabel(r.method)),
      datasets: SOURCES.map(([key, label], i) => ({
        label: `${label} (${(d.by_source.find((x) => x.source === key)?.pairs ?? 0).toLocaleString("en")} pairs)`,
        data: fpMethods.map((m) => rate(m, key)), backgroundColor: SOURCE_COLORS[i],
        borderRadius: 4, borderColor: "#FFFFFF", borderWidth: { left: 1, right: 1 },
      })),
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "top", align: "start", labels: { boxWidth: 12, boxHeight: 12 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}%` } },
      },
      scales: {
        y: { min: 0, max: 100, ticks: { callback: (v) => `${v}%` },
             title: axisTitle("False-positive rate (% of pairs)") },
        x: { grid: { display: false }, title: axisTitle("Method (best threshold)") },
      },
    },
  });
  // table views of the same numbers, for screen readers and exact values
  const pct = (v) => `${v.toFixed(1)}%`;
  dataTable("#f1-chart", ["Method", "Names", "Threshold", "Precision", "Recall", "F1"],
    best.map((r) => [methodLabel(r.method), r.normalized ? "normalized" : "raw", r.threshold.toFixed(2),
                     pct(r.precision * 100), pct(r.recall * 100), r.f1.toFixed(3)]));
  dataTable("#fp-chart", ["Method", ...SOURCES.map(([, l]) => l)],
    fpMethods.map((m) => [methodLabel(m.method), ...SOURCES.map(([k]) => pct(rate(m, k)))]));
}

/** <details> under a chart with its data as a table; text only via textContent. */
function dataTable(canvasSel, head, rows) {
  const box = $(canvasSel).closest(".chart-box");
  box.after(h("details", { class: "data-table" }, h("summary", {}, "Show data as a table"),
    h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, head.map((t, i) => h("th", { scope: "col", class: i ? "num" : null }, t)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, r.map((v, i) =>
        i ? h("td", { class: "num" }, v) : h("th", { scope: "row" }, v)))))))));
}
loadResults();

// ============================================================ Performance
// Colour = method (CATEGORICAL order from src/plots.py); solid = GIN index, dashed = none.
const BENCH_COLORS = { exact: "#2a78d6", trigram: "#eb6834", levenshtein: "#1baf7a",
                       dmetaphone: "#eda100", soundex: "#e87ba4" };

async function loadBenchmark() {
  const fail = (msg) => { const b = $("#bench-error"); b.textContent = msg; b.hidden = false; };
  if (!window.Chart) return fail("Chart.js did not load (web/vendor/chart.umd.min.js missing).");
  let d;
  try { d = await getJSON("/api/benchmark"); } catch (err) { return fail(err.message); }

  const sizes = [...new Set(d.rows.map((r) => r.n_records))].sort((a, b) => a - b);
  const methods = [...new Set(d.rows.map((r) => r.method))];
  const ms = (m, n, gin) => d.rows.find((r) => r.method === m && r.n_records === n && r.gin_index === gin)?.mean_ms ?? null;
  const k = (n) => `${n / 1000}k`;
  const title = (text) => ({ display: true, text, color: "#4B5563", font: { weight: 600 },
                             padding: { top: 8, bottom: 8 } });

  new Chart($("#bench-chart"), {
    type: "line",
    data: {
      labels: sizes.map(k),
      datasets: methods.flatMap((m) => [true, false].map((gin) => ({
        label: `${methodLabel(m)}, ${gin ? "GIN index" : "no index"}`,
        data: sizes.map((n) => ms(m, n, gin)),
        borderColor: BENCH_COLORS[m] || "#4B5563", backgroundColor: BENCH_COLORS[m] || "#4B5563",
        borderWidth: 2, borderDash: gin ? [] : [6, 4], pointRadius: 4, pointHoverRadius: 6,
      }))),
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "top", align: "start", labels: { boxWidth: 24, boxHeight: 2 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)} ms` } },
      },
      scales: {
        y: { type: "logarithmic", title: title("Mean query time (ms, log scale)"),
             ticks: { callback: (v) => ([1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].includes(v) ? `${v} ms` : "") } },
        x: { grid: { display: false }, title: title("Records in the table") },
      },
    },
  });

  dataTable("#bench-chart", ["Method", "Index", ...sizes.map((n) => `${k(n)} records (ms)`)],
    methods.flatMap((m) => [true, false].map((gin) => [methodLabel(m), gin ? "GIN" : "none",
      ...sizes.map((n) => (ms(m, n, gin) ?? NaN).toFixed(1))])));

  const largest = d.largest;
  $("#bench-largest").textContent = k(largest);
  const order = Object.keys(d.speedup).sort((a, b) => d.speedup[b] - d.speedup[a]);
  $("#bench-table").replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "table" },
    h("thead", {}, h("tr", {},
      h("th", { scope: "col" }, "Method"),
      h("th", { scope: "col", class: "num" }, "No index (ms)"),
      h("th", { scope: "col", class: "num" }, "GIN index (ms)"),
      h("th", { scope: "col", class: "num" }, "Speedup"))),
    h("tbody", {}, order.map((m) => h("tr", {},
      h("th", { scope: "row" }, methodLabel(m)),
      h("td", { class: "num" }, ms(m, largest, false).toFixed(1)),
      h("td", { class: "num" }, ms(m, largest, true).toFixed(1)),
      h("td", { class: "num" }, `${d.speedup[m].toFixed(1)}×`)))))));
}
loadBenchmark();

// =================================================================== Team
// The report link works only once docs/report.pdf exists; otherwise say so.
fetch("report.pdf", { method: "HEAD" }).then((r) => {
  if (!r.ok) { $("#report-link").hidden = true; $("#report-missing").hidden = false; }
}).catch(() => {});
