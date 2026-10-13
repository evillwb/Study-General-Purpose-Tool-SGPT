"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const state = {
  meta: null, library: [], plan: {}, exam: null, tab: "questions", analysis: null,
  mix: { easy: 30, medium: 50, hard: 20 },
  jobId: null, timer: null, ollamaModels: [], statusOk: false, open: new Set(),
};

// ---------- small helpers ----------------------------------------------------
async function api(path, options = {}) {
  if (options.json !== undefined) {
    options = { ...options, method: options.method || "POST", body: JSON.stringify(options.json),
                headers: { "Content-Type": "application/json" } };
  }
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 3500);
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...children.flat().filter((c) => c != null && c !== false));
  return node;
}

const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// Plain text from the AI -> safe HTML with **bold**, *italic* and line breaks.
const fmt = (s) => escapeHtml(s)
  .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
  .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
  .replace(/\n/g, "<br>");
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const letter = (i) => String.fromCharCode(65 + i);

const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem("sgpt:" + key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem("sgpt:" + key, JSON.stringify(value)); } catch {} },
};

// ---------- AI settings ----------------------------------------------------------
function aiSettings() {
  const s = store.get("ai", {});
  return { provider: "ollama", temperature: 0.7, seed: "", num_ctx: "16384", models: {}, ...s };
}
function saveAi(patch) { store.set("ai", { ...aiSettings(), ...patch }); }
function currentProvider() {
  return state.meta.providers.find((p) => p.id === aiSettings().provider) || state.meta.providers[0];
}
function currentModel() {
  const p = currentProvider();
  return aiSettings().models[p.id] || p.default_model;
}
function aiPayload() {
  const s = aiSettings();
  return { provider: currentProvider().id, model: currentModel(), temperature: s.temperature,
           seed: s.seed, num_ctx: s.num_ctx };
}

function renderSettings() {
  const p = currentProvider();
  const s = aiSettings();
  $("#provider").value = p.id;
  $("#key-row").hidden = !p.needs_key;
  $("#url-row").hidden = !p.editable_url;
  $("#ctx-row").hidden = p.id !== "ollama";
  $("#base-url").value = p.base_url || "";
  $("#api-key").value = "";
  $("#api-key").placeholder = p.key ? `Saved (${p.key}) · paste a new key to replace` : "Paste your API key";
  $("#key-hint").innerHTML = p.key_url
    ? `Get a key at <a href="${p.key_url}" target="_blank" rel="noopener">${new URL(p.key_url).host}</a>.`
    : p.id === "custom" ? "Optional. Works with LM Studio, vLLM, Mistral, Together and other OpenAI-compatible servers." : "";
  const privacy = $("#privacy");
  privacy.textContent = p.id === "ollama"
    ? "Runs on your computer. Your sources never leave this machine (except for internet search, if used)."
    : `The text of your sources is sent to ${p.label} to write the exam. API usage may cost money.`;
  privacy.className = p.id === "ollama" ? "note" : "note warn";
  $("#model").value = currentModel();
  $("#model").placeholder = p.default_model || "model name";
  $("#temperature").value = s.temperature;
  $("#temp-out").textContent = s.temperature;
  $("#seed").value = s.seed;
  $("#num_ctx").value = s.num_ctx;

  const search = state.meta.search;
  $("#engine").value = search.engine;
  const engine = search.engines.find((e) => e.id === search.engine);
  $("#engine-key-row").hidden = !engine.needs_key;
  $("#engine-key").value = "";
  $("#engine-key").placeholder = search.key ? `Saved (${search.key})` : "Paste your API key";
  $("#engine-name").textContent = engine.label.replace(/\s*\(.*\)/, "");
}

async function checkStatus() {
  const pill = $("#status");
  const p = currentProvider();
  pill.className = "status";
  $("#status-text").textContent = `Checking ${p.label.replace(/\s*\(.*\)/, "")}…`;
  $("#model-status").textContent = "";
  const s = await api(`/api/status?provider=${p.id}`).catch((e) => ({ ok: false, error: e.message, models: [] }));
  if (currentProvider().id !== p.id) return; // switched while waiting
  state.statusOk = s.ok;
  $("#model-options").replaceChildren(...s.models.map((m) => el("option", { value: m })));
  const model = currentModel();
  if (s.ok) {
    pill.classList.add("ok");
    $("#status-text").textContent = `${p.label.replace(/\s*\(.*\)/, "")} · ${model || "choose a model"}`;
    if (p.id === "ollama" && model && !s.models.includes(model) && !s.models.includes(model + ":latest")) {
      $("#model-status").innerHTML = `“${escapeHtml(model)}” is not installed. Run <code>ollama pull ${escapeHtml(model)}</code>.`;
    } else {
      $("#model-status").textContent = s.models.length ? `${plural(s.models.length, "model")} available.` : "";
    }
  } else {
    pill.classList.add("bad");
    $("#status-text").textContent = p.id === "ollama" ? "Ollama is not running" : `${p.label}: needs setup`;
    $("#model-status").textContent = s.error || "";
  }
  updateGenerate();
  renderStudyForm();
}

function wireSettings() {
  const dialog = $("#settings");
  const open = () => { renderSettings(); dialog.showModal(); };
  $("#open-settings").addEventListener("click", open);
  $("#status").addEventListener("click", open);
  $$("[data-open-settings]").forEach((b) => b.addEventListener("click", open));
  dialog.addEventListener("close", checkStatus);

  $("#provider").addEventListener("change", (e) => {
    saveAi({ provider: e.target.value });
    renderSettings();
    checkStatus();
  });
  $("#model").addEventListener("change", (e) => {
    const s = aiSettings();
    saveAi({ models: { ...s.models, [currentProvider().id]: e.target.value.trim() } });
    checkStatus();
  });
  $("#temperature").addEventListener("input", (e) => { $("#temp-out").textContent = e.target.value; saveAi({ temperature: e.target.value }); });
  $("#seed").addEventListener("change", (e) => saveAi({ seed: e.target.value }));
  $("#num_ctx").addEventListener("change", (e) => saveAi({ num_ctx: e.target.value }));

  $("#save-key").addEventListener("click", async () => {
    const key = $("#api-key").value.trim();
    if (!key) return toast("Paste a key first.");
    try {
      const r = await api(`/api/providers/${currentProvider().id}`, { json: { api_key: key } });
      currentProvider().key = r.key;
      renderSettings();
      toast("API key saved on this computer.");
      checkStatus();
    } catch (e) { toast(e.message); }
  });
  $("#save-url").addEventListener("click", async () => {
    try {
      await api(`/api/providers/${currentProvider().id}`, { json: { base_url: $("#base-url").value.trim() } });
      currentProvider().base_url = $("#base-url").value.trim();
      toast("Server URL saved.");
      checkStatus();
    } catch (e) { toast(e.message); }
  });
  const saveEngine = async (withKey) => {
    const engine = $("#engine").value;
    const body = { engine };
    if (withKey) body.api_key = $("#engine-key").value.trim();
    try {
      const r = await api("/api/search-settings", { json: body });
      state.meta.search.engine = engine;
      state.meta.search.key = r.key;
      renderSettings();
      if (withKey) toast("Search key saved.");
    } catch (e) { toast(e.message); }
  };
  $("#engine").addEventListener("change", () => saveEngine(false));
  $("#save-engine").addEventListener("click", () => saveEngine(true));
}

// ---------- Builder: topic + sources --------------------------------------------
const BUILDER_FIELDS = ["topic", "subject", "level", "language", "src-text", "src-links",
  "instructions", "minutes", "challenge"];

function saveBuilder() {
  const data = Object.fromEntries(BUILDER_FIELDS.map((id) => [id, $("#" + id).value]));
  data.web = $("input[name=web]:checked").value;
  data.structure = $("input[name=structure]:checked").value;
  data.difficulty = $("input[name=difficulty]:checked").value;
  data.plan = state.plan;
  data.verify = $("#verify").checked;
  data.mix = state.mix;
  store.set("builder", data);
}

function loadBuilder() {
  const data = store.get("builder", {});
  BUILDER_FIELDS.forEach((id) => { if (data[id] != null) $("#" + id).value = data[id]; });
  for (const name of ["web", "structure", "difficulty"]) {
    const input = data[name] && $(`input[name=${name}][value=${data[name]}]`);
    if (input) input.checked = true;
  }
  if (data.mix) state.mix = data.mix;
  if (data.verify === false) $("#verify").checked = false;
  state.plan = {};
  const defaults = Object.fromEntries(state.meta.default_plan.map((p) => [p.type, p]));
  for (const t of state.meta.question_types) {
    const saved = data.plan?.[t.id];
    state.plan[t.id] = {
      count: saved?.count ?? defaults[t.id]?.count ?? 0,
      marks: saved?.marks ?? defaults[t.id]?.marks ?? t.marks,
    };
  }
}

const LANG_SHORT = { en: "English", zh: "中文", ms: "Melayu" };

async function loadLibrary() {
  state.library = await api("/api/library").catch(() => []);
  const list = $("#file-list");
  list.replaceChildren(...state.library.map((f) => {
    let sub = f.pages ? `${plural(f.pages, "page")}` : `${Math.round((f.chars || 0) / 1000)}k characters`;
    if (f.ocr) sub += " · read with OCR";
    if (f.role === "paper" && f.questions != null) sub += ` · ${plural(f.questions, "question")} found`;
    const subEl = el("div", { class: "item-sub" }, sub);
    if (!f.readable) {
      subEl.textContent = f.error ? "Could not open this file" : "No text found. Will be skipped";
      subEl.classList.add("warn");
    }
    const role = el("select", { class: "role", "aria-label": `How to use ${f.name}`,
      onchange: (e) => updateFile(f.name, { role: e.target.value }) },
      el("option", { value: "paper", selected: f.role === "paper" }, "Past paper"),
      el("option", { value: "notes", selected: f.role !== "paper" }, "Notes"));
    const detected = (f.detected || []).map((c) => LANG_SHORT[c] || c).join(" + ");
    const lang = el("select", { class: "role lang", "aria-label": `Language of ${f.name}`,
      title: "The language this file is in. The exam is always written in the exam language.",
      onchange: (e) => updateFile(f.name, { language: e.target.value }) },
      el("option", { value: "auto", selected: f.language === "auto" }, detected ? `Auto: ${detected}` : "Auto"),
      ...Object.entries(LANG_SHORT).map(([c, label]) => el("option", { value: c, selected: f.language === c }, label)));
    const use = el("label", { class: "switch", title: f.use ? "Used" : "Not used" },
      el("input", { type: "checkbox", checked: f.use, "aria-label": `Use ${f.name}`,
        onchange: (e) => updateFile(f.name, { use: e.target.checked }) }),
      el("span"));
    return el("li", { class: f.use ? "" : "off" },
      el("span", { class: `file-icon ${f.type}` }, f.type),
      el("div", { class: "item-main" }, el("div", { class: "item-name", title: f.name }, f.name), subEl),
      el("div", { class: "file-selects" }, role, lang),
      el("div", { class: "file-actions" }, use,
        el("button", { class: "icon-btn", type: "button", title: "Remove", "aria-label": `Remove ${f.name}`,
          onclick: () => deleteFile(f.name) }, "✕")));
  }));
  updateSources();
  loadAnalysis();
}

async function loadAnalysis() {
  const r = await api("/api/analysis").catch(() => ({ papers: [], analysis: null }));
  state.analysis = r.analysis;
  state.analysisPapers = r.papers;
  renderAnalysisBar();
  renderDifficulty();
}

function renderAnalysisBar() {
  const bar = $("#analysis-bar");
  const papers = state.library.filter((f) => f.use && f.readable && f.role === "paper").length;
  bar.hidden = !papers;
  if (!papers) return;
  const btn = (label, onclick, primary) => el("button", { class: `btn small${primary ? " primary" : ""}`, type: "button", onclick }, label);
  bar.replaceChildren(state.analysis
    ? el("span", {}, "✓ ", el("b", {}, `${plural(state.analysis.papers.length, "past paper")} analysed`))
    : el("span", {}, "Analyse your past papers first to see their topics, layout and difficulty."),
    el("span", { class: "btns" }, state.analysis
      ? [btn("View analysis", showAnalysis), btn("Re-analyse", startAnalysis)]
      : [btn("Analyse past papers", startAnalysis, true)]));
}

async function startAnalysis() {
  if (state.jobId) return toast("Please wait for the current job to finish.");
  try { followJob(await api("/api/analyse", { json: { ...aiPayload(), language: $("#language").value } })); }
  catch (e) { toast(e.message); }
}

function showAnalysis() {
  if (!state.analysis) return;
  showView("create");
  showStage("analysis");
  renderAnalysis();
}

function mixBar(mix, big) {
  return el("div", { class: `mix-bar${big ? " big" : ""}` }, ["easy", "medium", "hard"].map((k) =>
    el("span", { class: k, style: `flex-grow:${mix[k]}`, title: `${k}: ${mix[k]}%` }, mix[k] >= 12 ? `${k[0].toUpperCase()}${k.slice(1)} ${mix[k]}%` : mix[k] ? `${mix[k]}%` : "")));
}

function renderAnalysis() {
  const a = state.analysis;
  const m = a.merged;
  const facts = [m.subject, m.level, m.duration_minutes && `${m.duration_minutes} min`,
    plural(m.sections.length, "section"),
    plural(m.sections.reduce((n, sec) => n + sec.question_count, 0), "question")].filter(Boolean);
  const topics = Object.entries(m.topic_counts || {}).slice(0, 30);
  const sectionTable = (sections) => el("table", { class: "analysis-table" },
    el("tr", {}, el("th", {}, "Section"), el("th", {}, "Questions"), el("th", {}, "Marks"), el("th", {}, "Question types")),
    sections.map((sec) => el("tr", {}, el("td", {}, sec.name), el("td", {}, String(sec.question_count)),
      el("td", {}, sec.marks ? String(sec.marks) : "–"), el("td", {}, sec.question_types.join(", ") || "–"))));
  $("#analysis").replaceChildren(
    el("div", {},
      el("h2", {}, "Past paper analysis"),
      el("p", { class: "muted" }, `${a.papers.map((p) => p.name).join(", ")} · analysed by ${a.model}`)),
    el("div", { class: "chips" }, facts.map((f) => el("span", { class: "chip" }, f))),
    el("p", { class: "hint" }, a.papers.map((p) => p.pages
      ? `${p.name}: read all ${plural(p.pages, "page")}` + (p.questions_found ? `, ${plural(p.questions_found, "question")}` : "")
        + (p.chapters?.length > 1 ? ` in ${plural(p.chapters.length, "chapter")}` : "") + (p.parts > 1 ? ` (analysed in ${p.parts} parts)` : "")
      : p.name).join(" · ")),
    m.difficulty && el("div", {}, el("h3", {}, "Difficulty"), mixBar(m.difficulty, true),
      m.difficulty_notes && el("p", { class: "hint" }, m.difficulty_notes)),
    el("div", {}, el("h3", {}, "Layout"), sectionTable(m.sections)),
    topics.length > 0 && el("div", {}, el("h3", {}, "Topics (how many papers test them)"),
      el("div", { class: "topic-chips" }, topics.map(([t, n]) => el("span", {}, t, n > 1 ? el("b", {}, `×${n}`) : null)))),
    el("div", { class: "analysis-grid" },
      m.command_words?.length > 0 && el("div", {}, el("h3", {}, "Command words"),
        el("div", { class: "topic-chips" }, m.command_words.map((w) => el("span", {}, w)))),
      m.style_notes && el("div", {}, el("h3", {}, "Question style"), el("p", {}, m.style_notes))),
    a.papers.length > 1 && el("div", {}, el("h3", {}, "Each paper"), a.papers.map((p) =>
      el("details", {}, el("summary", {}, p.name),
        p.difficulty && mixBar(p.difficulty), sectionTable(p.sections),
        p.chapters?.length > 1 && el("p", { class: "hint" }, `Chapters: ${p.chapters.join(" · ")}`)))),
    el("div", { class: "analysis-actions" },
      el("button", { class: "btn", type: "button", onclick: () => { $("input[name=structure][value=match]").checked = true; saveBuilder(); updateSources(); toast("The new exam will copy this layout."); } }, "Use this layout"),
      m.difficulty && el("button", { class: "btn", type: "button", onclick: () => { $("input[name=difficulty][value=past]").checked = true; saveBuilder(); renderDifficulty(); toast("The new exam will match this difficulty."); } }, "Use this difficulty"),
      el("button", { class: "btn primary", type: "button", onclick: startGeneration }, "Generate exam")));
}

// ---------- Builder: difficulty -----------------------------------------------------
const CHALLENGE_LABELS = { "-2": "Much easier", "-1": "Easier", 0: "Normal", 1: "Harder", 2: "Much harder" };

function currentMix() {
  const choice = $("input[name=difficulty]:checked").value;
  if (choice === "custom") {
    const total = state.mix.easy + state.mix.medium + state.mix.hard || 1;
    const mix = Object.fromEntries(Object.entries(state.mix).map(([k, v]) => [k, Math.round((v * 100) / total)]));
    mix.medium += 100 - mix.easy - mix.medium - mix.hard;
    return mix;
  }
  if (choice === "past") return state.analysis?.merged?.difficulty || state.meta.difficulty_mix.mixed;
  return state.meta.difficulty_mix[choice];
}

function renderDifficulty() {
  const pastInput = $("input[name=difficulty][value=past]");
  const hasPast = Boolean(state.analysis?.merged?.difficulty);
  pastInput.disabled = !hasPast;
  if (!hasPast && pastInput.checked) $("input[name=difficulty][value=mixed]").checked = true;
  const custom = $("input[name=difficulty]:checked").value === "custom";
  $("#mix-custom").hidden = !custom;
  $$("#mix-custom input").forEach((input) => {
    input.value = state.mix[input.dataset.level];
    input.nextElementSibling.textContent = `${currentMix()[input.dataset.level]}%`;
  });
  $("#mix-bar").replaceWith(Object.assign(mixBar(currentMix()), { id: "mix-bar" }));
  $("#challenge-out").textContent = CHALLENGE_LABELS[$("#challenge").value];
}

async function uploadFiles(files) {
  const ok = [...files].filter((f) => /\.(pdf|txt|md|markdown|png|jpe?g|webp)$/i.test(f.name));
  if (!ok.length) return toast("Use PDF, TXT, Markdown or image files.");
  const form = new FormData();
  ok.forEach((f) => form.append("files", f));
  toast(`Adding ${plural(ok.length, "file")}… scanned PDFs take a little longer (OCR).`);
  try {
    await api("/api/library", { method: "POST", body: form });
    await loadLibrary();
    toast(`Added ${plural(ok.length, "file")}.`);
  } catch (e) { toast(e.message); }
}

async function updateFile(name, patch) {
  await api(`/api/library/${encodeURIComponent(name)}`, { method: "PATCH", json: patch }).catch((e) => toast(e.message));
  loadLibrary();
}

async function deleteFile(name) {
  if (!confirm(`Remove “${name}”?`)) return;
  await api(`/api/library/${encodeURIComponent(name)}`, { method: "DELETE" }).catch((e) => toast(e.message));
  loadLibrary();
}

function links() { return $("#src-links").value.split("\n").map((s) => s.trim()).filter(Boolean); }

function updateSources() {
  const files = state.library.filter((f) => f.use && f.readable);
  const papers = files.filter((f) => f.role === "paper");
  const text = $("#src-text").value.trim();
  const urls = links();
  const web = $("input[name=web]:checked").value;
  const hasOwn = files.length || text || urls.length;
  const searching = web === "on" || (web === "auto" && !hasOwn);

  $("#src-files-n").textContent = files.length || "";
  $("#src-text-n").textContent = text ? "✓" : "";
  $("#src-links-n").textContent = urls.length || "";
  const pills = [];
  if (files.length) pills.push(el("span", { class: "pill" }, plural(files.length, "file")));
  if (text) pills.push(el("span", { class: "pill" }, "pasted text"));
  if (urls.length) pills.push(el("span", { class: "pill" }, plural(urls.length, "link")));
  if (searching) pills.push(el("span", { class: "pill web" }, "🌐 internet search"));
  if (!pills.length) pills.push(el("span", {}, "Only the AI's own knowledge will be used."));
  $("#source-summary").replaceChildren(...pills);

  const matchInput = $("input[name=structure][value=match]");
  matchInput.disabled = !papers.length;
  $("#match-option").title = papers.length ? "" : "Add a PDF and mark it as a past paper to use this";
  if (!papers.length && matchInput.checked) $("input[name=structure][value=custom]").checked = true;
  renderPlan();
}

// ---------- Builder: question plan ------------------------------------------------
function renderPlan() {
  const match = $("input[name=structure]:checked").value === "match";
  $("#plan").hidden = match;
  $("#match-note").hidden = !match;
  $("#plan").replaceChildren(...state.meta.question_types.map((t) => {
    const item = state.plan[t.id];
    const setCount = (n) => { item.count = Math.max(0, Math.min(50, n)); saveBuilder(); renderPlan(); };
    return el("div", { class: `plan-row${item.count ? "" : " zero"}` },
      el("span", { class: "name" }, t.label),
      el("span", { class: "stepper" },
        el("button", { type: "button", "aria-label": `Fewer ${t.label}`, onclick: () => setCount(item.count - 1) }, "−"),
        el("input", { type: "number", min: 0, max: 50, value: item.count, "aria-label": `${t.label} questions`,
          onchange: (e) => setCount(parseInt(e.target.value, 10) || 0) }),
        el("button", { type: "button", "aria-label": `More ${t.label}`, onclick: () => setCount(item.count + 1) }, "+")),
      el("label", { class: "marks-each" },
        el("input", { type: "number", min: 1, max: 50, value: item.marks, "aria-label": `Marks per ${t.label} question`,
          onchange: (e) => { item.marks = Math.max(1, parseInt(e.target.value, 10) || 1); saveBuilder(); renderPlan(); } }),
        "marks"));
  }));
  const papers = state.library.filter((f) => f.use && f.readable && f.role === "paper").length;
  const count = Object.values(state.plan).reduce((a, p) => a + p.count, 0);
  const marks = Object.values(state.plan).reduce((a, p) => a + p.count * p.marks, 0);
  $("#plan-summary").innerHTML = match
    ? `Same layout as your <b>${plural(papers, "past paper")}</b>`
    : `<b>${plural(count, "question")}</b> · <b>${plural(marks, "mark")}</b>`;
  updateGenerate();
}

function updateGenerate() {
  const match = $("input[name=structure]:checked")?.value === "match";
  const count = Object.values(state.plan).reduce((a, p) => a + p.count, 0);
  const hasTopic = $("#topic").value.trim() || $("#subject").value.trim();
  const hasOwn = state.library.some((f) => f.use && f.readable) || $("#src-text").value.trim() || links().length;
  let hint = "";
  if (state.jobId) hint = "Generating…";
  else if (!state.statusOk) hint = "Set up your AI first: click the status at the top right.";
  else if (!hasTopic && !hasOwn) hint = "Type a topic or add some sources.";
  else if (!match && !count) hint = "Choose at least one question.";
  $("#generate").disabled = Boolean(hint);
  $("#generate-hint").textContent = hint;
}

async function startGeneration() {
  saveBuilder();
  const plan = Object.entries(state.plan).filter(([, p]) => p.count > 0)
    .map(([type, p]) => ({ type, count: p.count, marks: p.marks }));
  const payload = {
    ...aiPayload(),
    topic: $("#topic").value, subject: $("#subject").value, level: $("#level").value,
    language: $("#language").value, source_language: "auto",
    text: $("#src-text").value, urls: links().join("\n"), web: $("input[name=web]:checked").value,
    structure: $("input[name=structure]:checked").value, plan,
    difficulty: $("input[name=difficulty]:checked").value,
    difficulty_mix: currentMix(), challenge: Number($("#challenge").value),
    verify: $("#verify").checked,
    instructions: $("#instructions").value, minutes: $("#minutes").value,
  };
  try { followJob(await api("/api/generate", { json: payload })); }
  catch (e) { toast(e.message); }
}

// ---------- Jobs ----------------------------------------------------------------------
function showStage(panel) {
  for (const id of ["empty", "progress", "result", "analysis"]) $("#" + id).hidden = id !== panel;
  // On phones the stage sits below the builder, so bring it into view.
  if (panel !== "empty" && window.matchMedia("(max-width: 980px)").matches) {
    $(".stage").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function followJob(job) {
  state.jobId = job.id;
  updateGenerate();
  if (job.kind === "generate" || job.kind === "analyse") { showView("create"); showStage("progress"); }
  renderJob(job);
  clearInterval(state.timer);
  state.timer = setInterval(async () => {
    try { renderJob(await api(`/api/jobs/${state.jobId}`)); } catch { /* try again next tick */ }
  }, 1000);
}

const formatTime = (s) => (s >= 60 ? `${Math.floor(s / 60)} min ${s % 60}s` : `${s}s`);
// "2 min 10s · about 4 min left": time so far and the estimate from the finished steps.
function timeText(job) {
  if (!job.eta) return formatTime(job.elapsed);
  const left = job.eta < 60 ? "under a minute" : job.eta < 3600 ? `about ${Math.round(job.eta / 60)} min`
    : `about ${Math.floor(job.eta / 3600)} h ${Math.round((job.eta % 3600) / 60)} min`;
  return `${formatTime(job.elapsed)} · ${left} left`;
}

function renderJob(job) {
  if (job.kind === "generate" || job.kind === "analyse") {
    const pct = job.state === "done" ? 100 : Math.round((job.done / Math.max(job.total, 1)) * 100);
    $("#progress").classList.toggle("running", job.state === "running");
    $("#bar-fill").style.width = `${Math.max(pct, 3)}%`;
    $("#progress-steps").textContent = job.total > 1 ? `Step ${Math.min(job.done + 1, job.total)} of ${job.total}` : "";
    $("#elapsed").textContent = timeText(job);
    $("#progress-title").textContent = { running: job.kind === "analyse" ? "Analysing your past papers…" : "Writing your exam…", error: "Something went wrong",
      cancelled: "Stopped", done: "Finished" }[job.state];
    $("#progress-msg").textContent = job.state === "error" ? job.error : job.message;
    $("#cancel").hidden = job.state !== "running";
    const log = job.log.filter((m) => m !== "Done");
    const items = log.map((m, i) => {
      const warn = m.startsWith("⚠");
      const current = job.state === "running" && i === log.length - 1;
      return el("li", { class: warn ? "warn" : current ? "current" : "" }, warn ? m.slice(2) : m);
    });
    if (job.state === "error") items.push(el("li", { class: "err" }, job.error));
    $("#progress-log").replaceChildren(...items);
  }
  if (job.state === "running") return;
  clearInterval(state.timer);
  state.jobId = null;
  updateGenerate();
  if (job.kind === "regenerate") {
    $$(".qcard.busy").forEach((c) => c.classList.remove("busy"));
    if (job.state === "done") { toast("New question ready."); openExam(job.exam_id, { keepTab: true }); }
    else if (job.state === "error") toast(job.error);
  } else if (job.kind === "analyse") {
    if (job.state === "done") {
      state.analysis = job.result;
      renderAnalysisBar();
      renderDifficulty();
      showAnalysis();
    }
  } else if (job.state === "done") {
    toast("Your exam is ready.");
    loadExams();
    openExam(job.exam_id);
  }
}

// ---------- Exam view -----------------------------------------------------------------
async function openExam(id, { keepTab = false } = {}) {
  try { state.exam = await api(`/api/exams/${id}`); } catch (e) { return toast(e.message); }
  if (!keepTab) { state.tab = "questions"; state.open.clear(); }
  showView("create");
  showStage("result");
  renderExam();
}

function renderExam() {
  const x = state.exam;
  $("#exam-title").textContent = x.title;
  const language = state.meta.languages.find((l) => l.id === (x.language || "en"));
  const chips = [plural(x.questions.length, "question"), plural(x.total_marks, "mark"),
    `${x.duration_minutes} min`, x.difficulty && `${x.difficulty[0].toUpperCase()}${x.difficulty.slice(1)} difficulty`,
    language && language.id !== "en" && language.label, x.model && `AI: ${x.model}`].filter(Boolean);
  $("#exam-chips").replaceChildren(...chips.map((c) => el("span", { class: "chip" }, c)));
  $$("#export-menu a").forEach((a) => (a.href = `/api/exams/${x.id}/export?part=${a.dataset.part}&format=${a.dataset.format}`));
  $$(".result .tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === state.tab));

  const isCards = state.tab === "questions";
  $("#questions").hidden = !isCards;
  $("#sheet").hidden = isCards;
  if (isCards) renderQuestions();
  else $("#sheet").innerHTML = x.html[state.tab]; // rendered and escaped on the server

  const sources = x.sources || [];
  $("#sources-used").replaceChildren(...(sources.length ? [
    el("b", {}, "Sources used"),
    el("ul", {}, sources.map((s) => el("li", {}, s.url
      ? el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title) : s.title,
      el("span", { class: "muted" }, ` · ${{ paper: "past paper", notes: "notes", text: "pasted text", web: "web" }[s.kind] || s.kind}`)))),
  ] : []));
}

function typeLabel(id) { return state.meta.question_types.find((t) => t.id === id)?.label || id; }

function renderQuestions() {
  const x = state.exam;
  const nodes = [];
  x.sections.forEach((sec, index) => {
    const qs = x.questions.filter((q) => q.section === index);
    if (!qs.length) return;
    if (x.sections.length > 1) {
      nodes.push(el("div", { class: "section-head" }, el("h3", {}, sec.name),
        el("span", {}, `${plural(qs.length, "question")} · ${plural(qs.reduce((a, q) => a + q.marks, 0), "mark")}`)));
    }
    qs.forEach((q) => nodes.push(questionCard(q)));
  });
  $("#questions").replaceChildren(...nodes);
}

function correctOption(q) {
  if (q.type !== "mcq" && q.type !== "true_false") return -1;
  const fa = (q.final_answer || "").trim();
  const m = fa.match(/^\(?([A-H])\b[).:]?/);
  if (m) return m[1].charCodeAt(0) - 65;
  return q.options.findIndex((o) => fa.toLowerCase().startsWith(o.toLowerCase()) || o.toLowerCase() === fa.toLowerCase());
}

function questionCard(q) {
  const open = state.open.has(q.number);
  const correct = open ? correctOption(q) : -1;
  const card = el("article", { class: "qcard", "data-number": q.number },
    el("div", { class: "qhead" },
      el("span", { class: "qnum" }, `Q${q.number}`),
      el("span", { class: "tag" }, typeLabel(q.type)),
      el("span", { class: `tag ${q.difficulty}` }, q.difficulty),
      q.topic && el("span", { class: "tag" }, q.topic),
      q.check && el("span", { class: `tag ${q.check}`, title: q.check_note || "" },
        { verified: "✓ Checked", corrected: "✎ Corrected by check", flagged: "⚠ Check failed" }[q.check]),
      el("span", { class: "qmarks" }, plural(q.marks, "mark"))),
    el("div", { class: "qtext", html: fmt(q.question) }),
    q.options.length > 0 && el("ul", { class: "options" }, q.options.map((o, i) =>
      el("li", { class: i === correct ? "correct" : "" }, el("b", {}, letter(i)), el("span", { html: fmt(o) })))),
    q.parts.length > 0 && el("ul", { class: "parts" }, q.parts.map((p) =>
      el("li", {}, el("span", { class: "pl" }, `(${p.label})`), el("span", { html: fmt(p.text) }),
        el("span", { class: "pm" }, `[${p.marks}]`)))),
    open && answerBlock(q),
    el("div", { class: "qfoot" },
      el("button", { class: "btn ghost small", type: "button", onclick: () => { open ? state.open.delete(q.number) : state.open.add(q.number); renderQuestions(); } },
        open ? "Hide answer" : "Show answer"),
      el("span", { class: "spacer" }),
      el("button", { class: "btn ghost small", type: "button", onclick: () => editQuestion(q, card) }, "Edit"),
      el("button", { class: "btn ghost small", type: "button", onclick: () => regenerate(q, card) }, "↻ Regenerate"),
      el("button", { class: "btn ghost small danger", type: "button", onclick: () => deleteQuestion(q) }, "Delete")));
  return card;
}

function answerBlock(q) {
  return el("div", { class: "answer" },
    q.check_note && q.check !== "verified" && el("div", { class: "check-note", html:
      `<b>${q.check === "flagged" ? "The double-check found a problem" : "Corrected by the double-check"}:</b> ${fmt(q.check_note)}` }),
    q.final_answer && el("div", { class: "final", html: `<b>Answer:</b> ${fmt(q.final_answer)}` }),
    el("h4", {}, "Model answer"),
    el("div", { html: fmt(q.answer || "No answer was generated. Try ↻ Regenerate.") }),
    q.marking_points.length > 0 && el("h4", {}, "Marking scheme"),
    q.marking_points.length > 0 && el("ul", { class: "points" }, q.marking_points.map((p) =>
      el("li", {}, el("span", { html: fmt(p.point) }), el("span", {}, plural(p.marks, "mark"))))),
    q.accept && el("div", { class: "muted", html: `<b>Accept / do not accept:</b> ${fmt(q.accept)}` }));
}

function editQuestion(q, card) {
  const field = (label, name, value, rows) => el("label", { class: "field" }, label,
    el("textarea", { name, rows }, value || ""));
  const form = el("form", { class: "edit-form" },
    field("Question", "question", q.question, 4),
    q.type === "mcq" && field("Options (one per line)", "options", q.options.join("\n"), 4),
    field("Short answer", "final_answer", q.final_answer, 2),
    field("Model answer", "answer", q.answer, 6),
    !q.parts.length && el("label", { class: "field narrow" }, "Marks", el("input", { name: "marks", type: "number", min: 1, value: q.marks })),
    el("div", { class: "edit-actions" },
      el("button", { class: "btn", type: "button", onclick: () => renderQuestions() }, "Cancel"),
      el("button", { class: "btn primary", type: "submit" }, "Save")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    if (data.options != null) data.options = data.options.split("\n");
    try {
      state.exam = await api(`/api/exams/${state.exam.id}/questions/${q.number}`, { method: "PATCH", json: data });
      renderExam();
      toast("Saved.");
    } catch (err) { toast(err.message); }
  });
  card.replaceChildren(el("div", { class: "qhead" }, el("span", { class: "qnum" }, `Q${q.number}`), el("span", { class: "tag" }, "Editing")), form);
}

async function regenerate(q, card) {
  if (state.jobId) return toast("Please wait for the current job to finish.");
  card.classList.add("busy");
  try {
    followJob(await api(`/api/exams/${state.exam.id}/questions/${q.number}/regenerate`, { json: aiPayload() }));
    toast(`Writing a new question ${q.number}…`);
  } catch (e) { card.classList.remove("busy"); toast(e.message); }
}

async function deleteQuestion(q) {
  if (!confirm(`Delete question ${q.number}? The other questions will be renumbered.`)) return;
  try {
    state.exam = await api(`/api/exams/${state.exam.id}/questions/${q.number}`, { method: "DELETE" });
    state.open.clear();
    renderExam();
    loadExams();
  } catch (e) { toast(e.message); }
}

// ---------- My exams ---------------------------------------------------------------
async function loadExams() {
  const exams = await api("/api/exams").catch(() => []);
  $("#exam-count").textContent = exams.length || "";
  const grid = $("#exam-grid");
  if (!exams.length) {
    grid.replaceChildren(el("p", { class: "empty-note" }, "Exams you generate will appear here."));
    return;
  }
  grid.replaceChildren(...exams.map((x) => el("div", { class: "exam-card", tabindex: 0,
      onclick: () => openExam(x.id), onkeydown: (e) => e.key === "Enter" && openExam(x.id) },
    el("h3", {}, x.title),
    el("div", { class: "meta" }, `${plural(x.questions, "question")} · ${plural(x.marks, "mark")}`),
    el("div", { class: "row-end" },
      el("span", { class: "meta" }, new Date(x.created).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })),
      el("button", { class: "btn ghost small danger", type: "button", onclick: async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete “${x.title}”?`)) return;
        await api(`/api/exams/${x.id}`, { method: "DELETE" }).catch((err) => toast(err.message));
        if (state.exam?.id === x.id) { state.exam = null; showStage("empty"); }
        loadExams();
      } }, "Delete")))));
}

function showView(view) {
  $("#view-create").hidden = view !== "create";
  $("#view-library").hidden = view !== "library";
  $("#view-ocr").hidden = view !== "ocr";
  $("#view-convert").hidden = view !== "convert";
  $("#view-bank").hidden = view !== "bank";
  $("#view-study").hidden = view !== "study";
  $("#view-media").hidden = view !== "media";
  if (view === "media") renderMediaPage();
  if (view === "study") { loadStudyRecent(); renderStudyForm(); }
  if (view === "bank") loadBank();
  $$(".nav-link").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (view === "library") loadExams();
  if (view === "convert") loadConverted();
  pollDock();
}

// ---------- OCR only -------------------------------------------------------------------
const ocrState = { jobId: null, timer: null, results: [], files: {} };

async function startOcr(files) {
  const ok = [...files].filter((f) => /\.(pdf|png|jpe?g|webp|bmp|tiff?)$/i.test(f.name));
  if (!ok.length) return toast("Use PDF or image files.");
  if (ocrState.jobId) return toast("Please wait for the current OCR to finish.");
  const form = new FormData();
  ok.forEach((f) => { form.append("files", f); ocrState.files[f.name] = f; });
  form.append("force", $("#ocr-force").checked ? "true" : "false");
  try {
    const job = await api("/api/ocr", { method: "POST", body: form });
    ocrState.jobId = job.id;
    $("#ocr-progress").hidden = false;
    renderOcrJob(job);
    clearInterval(ocrState.timer);
    ocrState.timer = setInterval(async () => {
      try { renderOcrJob(await api(`/api/jobs/${ocrState.jobId}`)); } catch { /* retry next tick */ }
    }, 700);
  } catch (e) { toast(e.message); }
}

function renderOcrJob(job) {
  $("#ocr-msg").textContent = job.state === "error" ? job.error : `${job.message} · ${timeText(job)}`;
  $("#ocr-fill").style.width = `${Math.max(3, Math.round(((job.done + (job.state === "done" ? 1 : 0)) / Math.max(job.total, 1)) * 100))}%`;
  $("#ocr-cancel").hidden = job.state !== "running";
  if (job.state === "running") return;
  clearInterval(ocrState.timer);
  ocrState.jobId = null;
  if (job.state === "error") return toast(job.error);
  $("#ocr-progress").hidden = true;
  if (job.result?.length) {
    ocrState.results = [...job.result, ...ocrState.results];
    renderOcrResults();
    toast(job.state === "done" ? "Text extracted." : "Stopped. Showing the pages read so far.");
  }
}

function ocrText(file, withHeadings = file.pages.length > 1) {
  return file.pages.map((p) => (withHeadings ? `--- Page ${p.page} ---\n` : "") + p.text.trim()).join("\n\n") + "\n";
}

function ocrMarkdown(file) {
  // Two trailing spaces keep the scan's line breaks in Word/PDF.
  const body = (p) => p.text.trim().split("\n").map((l) => l.trimEnd()).join("  \n");
  return file.pages.length === 1 ? body(file.pages[0]) + "\n"
    : file.pages.map((p) => `## Page ${p.page}\n\n${body(p)}`).join("\n\n") + "\n";
}

async function exportText(markdown, format, title) {
  try {
    const res = await fetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown, format, title }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Export failed");
    const url = URL.createObjectURL(await res.blob());
    el("a", { href: url, download: `${title}.${format}` }).click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (e) { toast(e.message); }
}

// ---------- Study tools ---------------------------------------------------------------
const studyState = { tool: "notes", set: null, jobId: null, fc: null, quiz: null };
const STUDY_FIELDS = ["st-topic", "st-level", "st-language", "st-test", "st-style", "st-words", "st-count",
  "st-translate", "st-difficulty", "st-text", "st-urls", "st-web", "st-instructions"];
const TOOL_LABELS = { notes: "Make notes", flashcards: "Make flashcards", vocab: "Explain vocabulary",
  quiz: "Make quiz", grammar: "Make grammar test" };
const STYLE_HINTS = {
  guide: "Print-ready guide, chapter by chapter: key formulas in boxes, exam tips and traps. Uses your question bank and past-paper analysis for the patterns table and checklist.",
  chapter: "A chapter handout: a key-terms table (term, definition, example), then short bullet sections, comparison tables and arrow flows.",
};

function initStudy() {
  const m = state.meta.study;
  $("#st-style").replaceChildren(...Object.entries(m.note_styles).map(([id, label]) => el("option", { value: id }, label)));
  const groups = { en: "English", zh: "中文 (Chinese)", ms: "Bahasa Melayu" };
  $("#st-test").replaceChildren(...Object.entries(groups).map(([code, name]) => el("optgroup", { label: name },
    ...Object.entries(m.grammar_tests).filter(([id]) => id.startsWith(code + "_"))
      .map(([id, label]) => el("option", { value: id }, label.split(" · ")[1] || label)))));
  $("#st-language").replaceChildren(...state.meta.languages.map((l) => el("option", { value: l.id }, l.label)));
  $("#st-translate").append(...state.meta.languages.map((l) => el("option", { value: l.id }, l.label)));
  const saved = store.get("study", {});
  STUDY_FIELDS.forEach((id) => { if (saved[id] != null) $("#" + id).value = saved[id]; });
  if (saved.length) $(`input[name=st-length][value=${saved.length}]`).checked = true;
  $("#st-files").checked = Boolean(saved.files);
  studyState.tool = saved.tool || "notes";
  $$(".tool").forEach((b) => b.addEventListener("click", () => { studyState.tool = b.dataset.tool; saveStudy(); renderStudyForm(); }));
  $("#study-form").addEventListener("input", () => { saveStudy(); renderStudyForm(); });
  $("#st-generate").addEventListener("click", generateStudy);
  $("#sp-cancel").addEventListener("click", () => studyState.jobId && api(`/api/jobs/${studyState.jobId}/cancel`, { method: "POST" }).catch(() => {}));
  renderStudyForm();
}

function saveStudy() {
  const data = Object.fromEntries(STUDY_FIELDS.map((id) => [id, $("#" + id).value]));
  data.length = $("input[name=st-length]:checked").value;
  data.files = $("#st-files").checked;
  data.tool = studyState.tool;
  store.set("study", data);
}

function renderStudyForm() {
  const tool = studyState.tool;
  $$(".tool").forEach((b) => b.classList.toggle("active", b.dataset.tool === tool));
  $$("#study-form [data-for]").forEach((n) => (n.hidden = !n.dataset.for.split(" ").includes(tool)));
  $("#study-form-title").textContent = { notes: "Notes", flashcards: "Flashcards", vocab: "Vocabulary", quiz: "MCQ quiz", grammar: "Grammar test" }[tool];
  $("#st-generate-label").textContent = TOOL_LABELS[tool];
  $("#st-topic").placeholder = tool === "grammar" ? "Theme for the sentences (optional), e.g. school life" : "Topic, e.g. Cell division";
  $("#st-style-hint").textContent = STYLE_HINTS[$("#st-style").value] || "";
  $("#st-files-n").textContent = plural(state.library.filter((f) => f.use && f.readable).length, "file");
  const topic = $("#st-topic").value.trim();
  const own = $("#st-files").checked || $("#st-text").value.trim() || $("#st-urls").value.trim() || (tool === "vocab" && $("#st-words").value.trim());
  let hint = "";
  if (!state.statusOk) hint = "Set up your AI first: click the status at the top right.";
  else if (tool !== "grammar" && !topic && !own) hint = "Type a topic or add some sources.";
  else if (studyState.jobId || state.jobId) hint = "Working…";
  $("#st-hint").textContent = hint;
  $("#st-generate").disabled = Boolean(hint);
}

async function generateStudy() {
  saveStudy();
  const v = (id) => $("#" + id).value;
  const body = { ...aiPayload(), kind: studyState.tool, topic: v("st-topic"), level: v("st-level"),
    language: v("st-language"), count: v("st-count"), style: v("st-style"),
    length: $("input[name=st-length]:checked").value, words: v("st-words"), translate_to: v("st-translate"),
    difficulty: v("st-difficulty"), test: v("st-test"), instructions: v("st-instructions"),
    use_files: $("#st-files").checked, text: v("st-text"), urls: v("st-urls"), web: v("st-web") };
  let job;
  try { job = await api("/api/study/generate", { json: body }); } catch (e) { return toast(e.message); }
  studyState.jobId = job.id;
  renderStudyForm();
  studyShow("progress");
  const update = (j) => {
    $("#sp-title").textContent = { running: "Working on it…", error: "Something went wrong", cancelled: "Stopped", done: "Done" }[j.state];
    $("#sp-msg").textContent = j.state === "error" ? j.error : j.message;
    $("#sp-fill").style.width = `${Math.max(3, Math.round((j.done / Math.max(j.total, 1)) * 100))}%`;
    $("#sp-steps").textContent = j.total > 1 ? `Step ${Math.min(j.done + 1, j.total)} of ${j.total}` : "";
    $("#sp-elapsed").textContent = timeText(j);
    $("#sp-cancel").hidden = j.state !== "running";
  };
  update(job);
  job = await pollJob(job.id, update);
  studyState.jobId = null;
  renderStudyForm();
  if (job.state === "done") { loadStudyRecent(); openSet(job.result.id); }
  else if (job.state === "error") toast(job.error);
}

function studyShow(panel) {
  for (const id of ["study-empty", "study-progress", "study-view"]) $("#" + id).hidden = id !== `study-${panel}`;
  if (panel !== "empty" && window.matchMedia("(max-width: 980px)").matches) $("#view-study .stage").scrollIntoView({ behavior: "smooth" });
}

async function loadStudyRecent() {
  const sets = await api("/api/study").catch(() => []);
  const icons = { notes: "📝", flashcards: "🃏", vocab: "🔤", quiz: "⏱️", grammar: "✍️" };
  $("#study-recent").replaceChildren(...(sets.length ? sets.slice(0, 15).map((x) => el("li", { style: "cursor:pointer", onclick: () => openSet(x.id) },
    el("span", { style: "font-size:20px" }, icons[x.kind] || "📄"),
    el("div", { class: "item-main" }, el("div", { class: "item-name", title: x.title }, x.title),
      el("div", { class: "item-sub" }, `${state.meta.study.kinds[x.kind]}${x.size ? ` · ${x.size}` : ""} · ${new Date(x.created).toLocaleDateString()}`)),
    el("span"),
    el("button", { class: "icon-btn", type: "button", "aria-label": "Delete", onclick: async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete “${x.title}”?`)) return;
      await api(`/api/study/${x.id}`, { method: "DELETE" }).catch((err) => toast(err.message));
      if (studyState.set?.id === x.id) studyShow("empty");
      loadStudyRecent();
    } }, "✕"))) : [el("li", { class: "empty-note" }, "Nothing yet.")]));
}

async function openSet(id) {
  try { studyState.set = await api(`/api/study/${id}`); } catch (e) { return toast(e.message); }
  showView("study");
  studyShow("view");
  renderSet();
}

function exportButtons(set, formats) {
  return el("div", { class: "actions" }, formats.map((f) => el("a", { class: "btn small", href: `/api/study/${set.id}/export?format=${f}` },
    { docx: "Word", pdf: "PDF", md: "Markdown", csv: "CSV (Anki)" }[f])));
}

function renderSet() {
  const s = studyState.set;
  const head = el("div", { class: "sv-head" },
    el("div", {}, el("h1", {}, s.title), el("div", { class: "chips" },
      [state.meta.study.kinds[s.kind], s.style && state.meta.study.note_styles[s.style], s.model && `AI: ${s.model}`]
        .filter(Boolean).map((c) => el("span", { class: "chip" }, c)))),
    exportButtons(s, s.kind === "flashcards" || s.kind === "vocab" ? ["csv", "docx", "pdf", "md"] : ["docx", "pdf", "md"]));
  const body = { notes: renderNotes, flashcards: renderFlashcards, vocab: renderVocab, quiz: renderQuizStart, grammar: renderQuizStart }[s.kind](s);
  $("#study-view").replaceChildren(head, body);
}

// Notes
function renderNotes(s) {
  const sheet = el("article", { class: "sheet notes-sheet" });
  sheet.innerHTML = s.html; // rendered and escaped on the server
  if (s.style === "mindmap") mindmap(sheet);
  const qa = el("div", { class: "review" }, (s.qa || []).map((x) => el("div", { class: "qa" }, el("b", {}, `Q: ${x.question}`), el("div", { html: x.html }))));
  const input = el("input", { placeholder: "Ask a question about these notes…", "aria-label": "Question" });
  const ask = async () => {
    const question = input.value.trim();
    if (!question) return;
    let job;
    try { job = await api(`/api/study/${s.id}/ask`, { json: { ...aiPayload(), question } }); } catch (e) { return toast(e.message); }
    input.value = "";
    const pending = el("div", { class: "qa" }, el("b", {}, `Q: ${question}`), el("p", { class: "muted" }, "Thinking…"));
    qa.append(pending);
    job = await pollJob(job.id, () => {});
    if (job.state === "done") { pending.replaceChildren(el("b", {}, `Q: ${question}`), el("div", { html: job.result.html })); (s.qa ||= []).push(job.result); }
    else pending.replaceChildren(el("b", {}, `Q: ${question}`), el("p", {}, job.error || "Stopped."));
  };
  input.addEventListener("keydown", (e) => e.key === "Enter" && ask());
  const reuse = (tool) => {
    studyState.tool = tool;
    $("#st-text").value = s.markdown;
    $("#st-topic").value = $("#st-topic").value || s.title;
    $("#st-files").checked = false;
    saveStudy(); renderStudyForm();
    toast(`Notes added as the source. Click “${TOOL_LABELS[tool]}”.`);
  };
  return el("div", { class: "study-view" },
    el("div", { class: "actions" },
      el("button", { class: "btn small", type: "button", onclick: () => reuse("flashcards") }, "🃏 Flashcards from these"),
      el("button", { class: "btn small", type: "button", onclick: () => reuse("quiz") }, "⏱️ Quiz from these"),
      el("button", { class: "btn small", type: "button", onclick: () => {
        $("#src-text").value = s.markdown; $("#topic").value = $("#topic").value || s.title;
        saveBuilder(); updateSources(); showView("create"); toast("Notes added as an exam source.");
      } }, "📄 Exam from these"),
      el("button", { class: "btn small", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(s.markdown); toast("Copied."); } catch { toast("Copy failed."); }
      } }, "Copy"),
      el("button", { class: "btn small", type: "button", onclick: () => printNode(sheet) }, "Print")),
    sheet,
    el("h3", {}, "Ask about these notes"), el("div", { class: "ask-box" }, input, el("button", { class: "btn primary", type: "button", onclick: ask }, "Ask")), qa);
}

function printNode(node) {
  const w = window.open("", "_blank");
  if (!w) return toast("Allow pop-ups to print.");
  w.document.write(`<!doctype html><meta charset="utf-8"><title>${escapeHtml(studyState.set.title)}</title>
    <style>body{font:15px/1.55 Georgia,"Noto Serif SC",serif;max-width:760px;margin:24px auto;color:#111}
    h1,h2{color:#1f3f7a}h2{border-bottom:1.5px solid #1f3f7a}blockquote{background:#f2f3f5;border:1px solid #c5cad3;margin:8px 0;padding:8px 12px}
    table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #ccc;padding:4px 6px;text-align:left}</style>${node.innerHTML}`);
  w.document.close();
  w.focus();
  w.print();
}

function mindmap(sheet) {
  const root = sheet.querySelector("ul > li");
  if (!root) return;
  const title = root.childNodes[0]?.textContent.trim() || studyState.set.title;
  const colours = ["#4f46e5", "#0891b2", "#16a34a", "#d97706", "#db2777", "#7c3aed", "#dc2626", "#0d9488"];
  const branches = [...(root.querySelector(":scope > ul")?.children || [])].map((li, i) =>
    el("div", { class: "mm-branch", style: `--b:${colours[i % colours.length]}` },
      el("b", {}, li.childNodes[0]?.textContent.trim() || ""),
      li.querySelector("ul") ? el("ul", { html: li.querySelector("ul").innerHTML }) : null));
  sheet.replaceChildren(el("div", { class: "mindmap" }, el("div", { class: "mm-root" }, title), el("div", { class: "mm-branches" }, branches)));
}

// Flashcards (also used to practise vocabulary)
function renderFlashcards(s, cards = s.cards) {
  const fc = studyState.fc = { cards: [...cards], i: 0, known: 0, learning: 0, flipped: false };
  const wrap = el("div", { class: "fc-stage" });
  const draw = () => {
    const c = fc.cards[fc.i];
    const card = el("button", { class: `flashcard${fc.flipped ? " flipped" : ""}`, type: "button", "aria-label": "Flip card",
      onclick: () => { fc.flipped = !fc.flipped; card.classList.toggle("flipped", fc.flipped); } },
      el("div", { class: "fc-inner" },
        el("div", { class: "fc-face fc-front" }, el("span", { class: "fc-label" }, "Front"), el("div", { html: fmt(c.front) })),
        el("div", { class: "fc-face fc-back" }, el("span", { class: "fc-label" }, "Back"), el("div", { html: fmt(c.back) }))));
    const go = (d) => { fc.i = (fc.i + d + fc.cards.length) % fc.cards.length; fc.flipped = false; draw(); };
    const mark = (known) => { known ? fc.known++ : fc.learning++; if (!known) fc.cards.push(c); go(1); };
    wrap.replaceChildren(card,
      el("div", { class: "fc-controls" },
        el("button", { class: "btn", type: "button", onclick: () => go(-1) }, "←"),
        el("span", { class: "fc-count" }, `${fc.i + 1} / ${fc.cards.length}`),
        el("button", { class: "btn", type: "button", onclick: () => go(1) }, "→")),
      el("div", { class: "fc-controls" },
        el("button", { class: "btn", type: "button", onclick: () => mark(false) }, "😕 Still learning"),
        el("button", { class: "btn primary", type: "button", onclick: () => mark(true) }, "✅ I knew it"),
        el("button", { class: "btn ghost", type: "button", onclick: () => { fc.cards.sort(() => Math.random() - 0.5); fc.i = 0; fc.flipped = false; draw(); } }, "🔀 Shuffle")),
      el("p", { class: "fc-score" }, `Knew ${fc.known} · still learning ${fc.learning} · Space flips, ← → move`));
  };
  draw();
  const all = el("details", {}, el("summary", {}, "All cards"),
    el("div", { class: "fc-grid" }, cards.map((c) => el("div", {}, el("b", { html: fmt(c.front) }), el("span", { html: fmt(c.back) })))));
  return el("div", { class: "study-view" }, wrap, all);
}

document.addEventListener("keydown", (e) => {
  if ($("#view-study").hidden || !studyState.fc || !document.querySelector(".flashcard") || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) return;
  if (e.key === " ") { e.preventDefault(); document.querySelector(".flashcard").click(); }
  if (e.key === "ArrowRight") document.querySelector(".fc-controls .btn:last-child")?.click();
  if (e.key === "ArrowLeft") document.querySelector(".fc-controls .btn:first-child")?.click();
});

// Vocabulary
function renderVocab(s) {
  const lang = state.meta.languages.find((l) => l.id === s.translate_to);
  const table = el("table", { class: "vocab-table" },
    el("tr", {}, ["Word", "Meaning", "Example", lang && `In ${lang.label}`, "Synonyms"].filter(Boolean).map((h) => el("th", {}, h))),
    s.words.map((w) => el("tr", {},
      el("td", {}, w.word, el("div", { class: "pos" }, w.part_of_speech)),
      el("td", {}, w.meaning), el("td", {}, el("em", {}, w.example)),
      lang && el("td", {}, w.translation), el("td", {}, (w.synonyms || []).join(", ")))));
  return el("div", { class: "study-view" },
    el("div", { class: "actions" }, el("button", { class: "btn primary small", type: "button", onclick: () => {
      const cards = s.words.map((w) => ({ front: w.word, back: `(${w.part_of_speech}) ${w.meaning}${w.translation ? `\n${w.translation}` : ""}${w.example ? `\n\n“${w.example}”` : ""}` }));
      $("#study-view").replaceChildren($("#study-view").firstChild, renderFlashcards(s, cards));
    } }, "🃏 Practise as flashcards")),
    el("div", { class: "table-wrap" }, table));
}

// Quiz and grammar runner
function renderQuizStart(s) {
  const best = store.get(`best:${s.id}`, null);
  const n = s.items.length;
  const limit = el("select", { "aria-label": "Time limit" },
    el("option", { value: "0" }, "No time limit"),
    [5, 10, 15, 20, 30, 45, 60].map((m) => el("option", { value: m, selected: m === Math.max(5, Math.ceil(n * (s.kind === "quiz" ? 1 : 0.75) / 5) * 5) }, `${m} minutes`)));
  return el("div", { class: "quiz-start" },
    el("p", {}, `${plural(n, "question")}`, s.kind === "grammar" ? ` · ${state.meta.study.grammar_tests[s.test]}` : "",
      best ? ` · your best: ${best.score}/${best.total}` : ""),
    el("label", { class: "field" }, "Time limit", limit),
    el("p", { class: "hint" }, s.kind === "grammar" && s.test === "ms_error"
      ? "Pilih bahagian (A, B, C atau D) yang mengandungi kesalahan."
      : s.kind === "grammar" ? "Type the correct form of the word in each gap." : "Choose one answer for each question."),
    el("button", { class: "btn primary big", type: "button", style: "max-width:260px", onclick: () => startQuiz(s, Number(limit.value)) }, "Start"));
}

function startQuiz(s, minutes, items = s.items) {
  clearInterval(studyState.quiz?.timer);
  const q = studyState.quiz = { s, items, i: 0, answers: items.map(() => null), minutes, started: Date.now(), done: false };
  if (minutes) q.timer = setInterval(() => {
    const left = minutes * 60 - Math.floor((Date.now() - q.started) / 1000);
    const t = $("#quiz-timer");
    if (t) { t.textContent = clock(Math.max(left, 0)); t.classList.toggle("low", left <= 60); }
    if (left <= 0) { toast("Time's up!"); finishQuiz(); }
  }, 500);
  else q.timer = setInterval(() => { const t = $("#quiz-timer"); if (t) t.textContent = clock(Math.floor((Date.now() - q.started) / 1000)); }, 1000);
  drawQuiz();
}

const clock = (sec) => `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;

function itemView(item, answer, onAnswer, review) {
  if (item.type === "mcq") {
    return el("div", { class: "quiz-q" }, el("div", { class: "qtext", html: fmt(item.question) }),
      item.options.map((o, i) => el("button", { type: "button", disabled: review,
        class: `choice${answer === i ? " selected" : ""}${review && i === item.answer ? " right" : ""}${review && answer === i && i !== item.answer ? " wrong" : ""}`,
        onclick: () => onAnswer(i) }, el("b", {}, letter(i)), el("span", { html: fmt(o) }))));
  }
  if (item.type === "error") {
    return el("div", { class: "quiz-q" }, el("div", { class: "segments" }, item.segments.map((seg, i) =>
      el("button", { type: "button", disabled: review,
        class: `segment${answer === i ? " selected" : ""}${review && i === item.answer ? " right" : ""}${review && answer === i && i !== item.answer ? " wrong" : ""}`,
        onclick: () => onAnswer(i) }, seg, el("sup", {}, letter(i))), " ")));
  }
  const [before, after] = item.sentence.split(/_{3,}/);
  const input = el("input", { class: "fill-input", value: answer ?? "", disabled: review, "aria-label": "Your answer",
    oninput: (e) => onAnswer(e.target.value) });
  return el("div", { class: "quiz-q" }, el("div", { class: "qtext" }, before, input, after ?? ""));
}

const norm = (t) => String(t ?? "").toLowerCase().replace(/[’']/g, "'").replace(/[.,!?;:"]+$/g, "").replace(/\s+/g, " ").trim();
function isRight(item, answer) {
  if (answer == null || answer === "") return false;
  if (item.type === "fill") return [item.answer, ...(item.alternatives || [])].some((a) => norm(a) === norm(answer));
  return answer === item.answer;
}

function drawQuiz() {
  const q = studyState.quiz;
  const item = q.items[q.i];
  const palette = el("div", { class: "palette" }, q.items.map((_, i) => el("button", { type: "button",
    class: `${q.answers[i] != null && q.answers[i] !== "" ? "done" : ""}${i === q.i ? " current" : ""}`,
    onclick: () => { q.i = i; drawQuiz(); } }, i + 1)));
  const view = itemView(item, q.answers[q.i], (a) => {
    q.answers[q.i] = a;
    if (item.type !== "fill") { drawQuiz(); }
    else palette.children[q.i].classList.toggle("done", a !== "");
  }, false);
  $("#study-view").replaceChildren($("#study-view").firstChild,
    el("div", { class: "quiz-bar" },
      el("b", {}, `Question ${q.i + 1} of ${q.items.length}`),
      el("span", { class: "timer", id: "quiz-timer" }, q.minutes ? clock(q.minutes * 60) : "00:00"),
      el("button", { class: "btn primary", type: "button", onclick: () => {
        const left = q.answers.filter((a) => a == null || a === "").length;
        if (!left || confirm(`${plural(left, "question")} not answered. Finish anyway?`)) finishQuiz();
      } }, "Finish")),
    palette, view,
    el("div", { class: "quiz-nav" },
      el("button", { class: "btn", type: "button", disabled: q.i === 0, onclick: () => { q.i--; drawQuiz(); } }, "← Previous"),
      el("button", { class: "btn", type: "button", disabled: q.i === q.items.length - 1, onclick: () => { q.i++; drawQuiz(); } }, "Next →")));
  view.querySelector("input")?.focus();
}

function finishQuiz() {
  const q = studyState.quiz;
  if (!q || q.done) return;
  q.done = true;
  clearInterval(q.timer);
  const used = Math.floor((Date.now() - q.started) / 1000);
  const right = q.items.filter((it, i) => isRight(it, q.answers[i])).length;
  const total = q.items.length;
  const best = store.get(`best:${q.s.id}`, null);
  if (q.items === q.s.items && (!best || right > best.score)) store.set(`best:${q.s.id}`, { score: right, total });
  const pct = Math.round((right / total) * 100);
  const wrong = q.items.filter((it, i) => !isRight(it, q.answers[i]));
  const key = (it) => it.type === "mcq" ? `${letter(it.answer)}. ${it.options[it.answer]}` : it.type === "error" ? `${letter(it.answer)} → ${it.correction}` : it.answer;
  const shown = (it, a) => a == null || a === "" ? "no answer" : it.type === "mcq" ? `${letter(a)}. ${it.options[a]}` : it.type === "error" ? letter(a) : a;
  $("#study-view").replaceChildren($("#study-view").firstChild,
    el("div", { class: "score" },
      el("div", { class: "score-ring", style: `--p:${pct}` }, el("span", {}, `${pct}%`)),
      el("div", {}, el("h2", {}, `${right} / ${total} correct`), el("p", { class: "muted" }, `Time: ${clock(used)}${q.minutes ? ` of ${q.minutes}:00` : ""}`)),
      el("div", { class: "actions" },
        el("button", { class: "btn", type: "button", onclick: () => startQuiz(q.s, q.minutes) }, "Try again"),
        wrong.length > 0 && el("button", { class: "btn primary", type: "button", onclick: () => startQuiz(q.s, q.minutes ? Math.max(1, Math.ceil(wrong.length * q.minutes / total)) : 0, wrong) }, `Practise the ${wrong.length} wrong`))),
    el("div", { class: "review" }, q.items.map((it, i) => {
      const ok = isRight(it, q.answers[i]);
      return el("div", { class: "qcard" },
        el("div", { class: "qhead" }, el("span", { class: "qnum" }, `Q${i + 1}`),
          el("span", { class: `tag ${ok ? "verified" : "flagged"}` }, ok ? "✓ Correct" : "✗ Wrong"),
          it.checked && el("span", { class: "tag" }, it.checked === "corrected" ? "✎ Key corrected by double-check" : "✓ Double-checked")),
        itemView(it, q.answers[i], () => {}, true),
        !ok && el("div", { class: "your" }, `Your answer: ${shown(it, q.answers[i])} · Correct: `, el("b", {}, key(it))),
        it.explanation && el("div", { class: "explain", html: fmt(it.explanation) }));
    })));
}

// ---------- Generic job polling ---------------------------------------------------------
function pollJob(id, onUpdate) {
  return new Promise((resolve) => {
    const timer = setInterval(async () => {
      let job;
      try { job = await api(`/api/jobs/${id}`); } catch { return; }
      onUpdate(job);
      if (job.state !== "running") { clearInterval(timer); resolve(job); }
    }, 800);
  });
}

// ---------- Question bank ------------------------------------------------------------
const bankState = { bank: null, papers: [], tab: "chapters", chapter: "", busy: false, open: new Set() };

async function loadBank() {
  const r = await api("/api/bank").catch(() => ({ papers: [], bank: null }));
  bankState.papers = r.papers;
  bankState.bank = r.bank;
  renderBank();
}

function bankProgress(job) {
  $("#bank-progress").hidden = job.state !== "running";
  $("#bank-msg").textContent = job.message;
  $("#bank-steps").textContent = (job.total > 1 ? `Step ${Math.min(job.done + 1, job.total)} of ${job.total} · ` : "") + timeText(job);
  bankState.jobId = job.id;
  $("#bank-fill").style.width = `${Math.max(3, Math.round((job.done / Math.max(job.total, 1)) * 100))}%`;
}

async function runBankJob(path, body) {
  if (bankState.busy || state.jobId) return toast("Please wait for the current job to finish.");
  let job;
  try { job = await api(path, { json: { ...aiPayload(), ...body } }); } catch (e) { return toast(e.message); }
  bankState.busy = true;
  renderBank();
  bankProgress(job);
  job = await pollJob(job.id, bankProgress);
  bankState.busy = false;
  $("#bank-progress").hidden = true;
  if (job.state === "error") toast(job.error);
  if (job.state === "done") { bankState.bank = job.result; toast(job.kind === "bank" ? "Questions sorted." : "Answers added."); }
  renderBank();
}

function bankVisible() {
  const b = bankState.bank;
  const query = $("#bank-search").value.trim().toLowerCase();
  const sort = $("#bank-sort").value;
  const n = Number($("#bank-n").value);
  const match = (q) => (!bankState.chapter || q.chapter === bankState.chapter)
    && (!query || `${q.text} ${q.topic} ${q.paper}`.toLowerCase().includes(query));
  const groups = [];
  for (const chapter of b.chapters) {
    let qs = b.questions.filter((q) => q.chapter === chapter && match(q));
    if (bankState.tab === "hardest") {
      qs = [...qs].sort((x, y) => y.difficulty - x.difficulty || (y.marks || 0) - (x.marks || 0)).slice(0, n);
    } else if (sort === "hard") qs = [...qs].sort((x, y) => y.difficulty - x.difficulty);
    else if (sort === "marks") qs = [...qs].sort((x, y) => (y.marks || 0) - (x.marks || 0));
    if (qs.length) groups.push([chapter, qs]);
  }
  return groups;
}

function renderBank() {
  const b = bankState.bank;
  const note = $("#bank-note");
  $("#bank-build").disabled = bankState.busy || !bankState.papers.length;
  $("#bank-build").textContent = b ? "Re-sort" : "Sort my past-year questions";
  note.hidden = Boolean(b) && bankState.papers.length > 0;
  note.textContent = !bankState.papers.length
    ? "Add your past-year papers first: on the Create page, under Sources → Files, add PDFs and mark them as “Past paper”."
    : `${plural(bankState.papers.length, "past paper")} ready: ${bankState.papers.join(", ")}. Click “Sort my past-year questions”.`;
  $("#bank-body").hidden = !b;
  if (!b) return;
  $("#bank-answers").disabled = bankState.busy;
  $("#bank-n").hidden = bankState.tab !== "hardest";
  $("#bank-sort").hidden = bankState.tab === "hardest";
  $("#bank-view").hidden = !bankState.bank.questions.some((q) => q.image);
  $$("[data-bank-tab]").forEach((t) => t.classList.toggle("active", t.dataset.bankTab === bankState.tab));
  const chapterSelect = $("#bank-chapter");
  if (chapterSelect.options.length !== b.chapters.length + 1) {
    chapterSelect.replaceChildren(el("option", { value: "" }, "All chapters"), ...b.chapters.map((c) => el("option", { value: c }, c)));
  }
  chapterSelect.value = bankState.chapter;
  const n = $("#bank-n").value;
  $$("#bank-export a").forEach((a) => (a.href = `/api/bank/export?view=${bankState.tab}&n=${n}&format=${a.dataset.format}`));

  $("#bank-chips").replaceChildren(...b.chapters.map((c) => {
    const qs = b.questions.filter((q) => q.chapter === c);
    const avg = qs.reduce((a, q) => a + q.difficulty, 0) / (qs.length || 1);
    return el("button", { class: `bank-chip${bankState.chapter === c ? " active" : ""}`, type: "button",
      onclick: () => { bankState.chapter = bankState.chapter === c ? "" : c; renderBank(); } },
      el("b", {}, c), el("small", {}, `${plural(qs.length, "question")} · avg difficulty ${avg.toFixed(1)}`));
  }));

  const groups = bankVisible();
  const nodes = [];
  for (const [chapter, qs] of groups) {
    nodes.push(el("div", { class: "section-head" }, el("h3", {}, chapter), el("span", {}, plural(qs.length, "question"))));
    qs.forEach((q, i) => nodes.push(bankCard(q, bankState.tab === "hardest" ? i + 1 : null)));
  }
  if (!nodes.length) nodes.push(el("p", { class: "empty-note" }, "No questions match."));
  $("#bank-list").replaceChildren(...nodes);
}

function bankCard(q, rank) {
  const open = bankState.open.has(q.id);
  return el("article", { class: "qcard" },
    el("div", { class: "qhead" },
      rank && el("span", { class: "rank" }, `#${rank}`),
      el("span", { class: "qnum" }, `Q${q.number}`),
      el("span", { class: "tag" }, q.paper + (q.section ? ` · ${q.section}` : "") + (q.page ? ` · p.${q.page}` : "")),
      el("span", { class: "tag" }, typeLabel(q.type)),
      q.topic && el("span", { class: "tag" }, q.topic),
      q.check && el("span", { class: `tag ${q.check}` }, { verified: "✓ Checked", corrected: "✎ Corrected by check", flagged: "⚠ Check failed" }[q.check]),
      el("span", { class: "qmarks" },
        el("span", { class: "diff", title: "Difficulty out of 10" }, el("span", { class: "diff-bar" }, el("span", { style: `width:${q.difficulty * 10}%` })), `${q.difficulty}/10`),
        q.marks ? ` · ${plural(q.marks, "mark")}` : "")),
    q.image && !bankState.textOnly
      ? el("img", { class: "qpicture", src: `/api/bank/image/${q.image}`, alt: q.text.slice(0, 200), loading: "lazy" })
      : el("div", { class: "qtext", html: fmt(q.text) }),
    q.reason && el("div", { class: "why" }, (rank ? "Why it's hard: " : "") + q.reason),
    open && q.answer && answerBlock({ ...q, accept: q.accept || "", marking_points: q.marking_points || [] }),
    q.answer && el("div", { class: "qfoot" }, el("button", { class: "btn ghost small", type: "button",
      onclick: () => { open ? bankState.open.delete(q.id) : bankState.open.add(q.id); renderBank(); } }, open ? "Hide answer" : "Show answer")));
}

// ---------- Convert --------------------------------------------------------------------
const convState = { files: [], target: "pdf", jobId: null, timer: null };
const CONV_TARGETS = [["pdf", "PDF"], ["docx", "Word"], ["txt", "Text"], ["md", "Markdown"], ["html", "Web page"],
  ["png", "Images"], ["merged-pdf", "Merge into one PDF"], ["searchable-pdf", "Searchable PDF (OCR)"]];

function ext(name) { return (name.match(/\.[^.]+$/) || [""])[0].toLowerCase(); }

function renderConvert() {
  const info = state.meta.convert;
  $("#lo-note").textContent = info.office?.length ? ` · Office files via Microsoft ${info.office.join(", ")}`
    : info.libreoffice ? " · Office files via LibreOffice" : "";
  $("#conv-targets").replaceChildren(...CONV_TARGETS.map(([id, label]) => el("label", {},
    el("input", { type: "radio", name: "conv-target", value: id, checked: convState.target === id,
      onchange: () => { convState.target = id; renderConvert(); } }),
    el("span", {}, label))));
  $("#conv-files").replaceChildren(...convState.files.map((f, i) => el("li", {},
    el("span", { class: `file-icon ${ext(f.name).slice(1)}` }, ext(f.name).slice(1, 5)),
    el("div", { class: "item-main" }, el("div", { class: "item-name" }, f.name),
      el("div", { class: "item-sub" }, `${Math.max(1, Math.round(f.size / 1024))} KB`)),
    el("span"),
    el("button", { class: "icon-btn", type: "button", "aria-label": `Remove ${f.name}`,
      onclick: () => { convState.files.splice(i, 1); renderConvert(); } }, "✕"))));
  const bad = convState.files.filter((f) => !info.inputs.includes(ext(f.name)));
  const office = convState.files.filter((f) => [".doc", ".rtf", ".odt", ".pptx", ".ppt", ".odp", ".xlsx", ".xls", ".ods"].includes(ext(f.name)));
  let hint = "";
  if (bad.length) hint = `Can't convert: ${bad.map((f) => f.name).join(", ")}`;
  else if (office.length && !info.libreoffice && !info.office?.length) hint = "Old Word, PowerPoint and Excel files need Microsoft Office or LibreOffice (free, libreoffice.org) installed.";
  else if (convState.target === "pdf" && convState.files.some((f) => ext(f.name) === ".docx") && !info.libreoffice && !info.office?.length)
    hint = "Word → PDF keeps headings, tables and pictures. For an exact copy (same fonts and page breaks), install Microsoft Word or LibreOffice (free).";
  else if (convState.target === "docx" && convState.files.some((f) => /^\.(pdf|png|jpe?g|webp|bmp|tiff?|gif)$/.test(ext(f.name))))
    hint = "Keeps the layout. Scanned pages and photos are rebuilt with OCR: the text in the same place and size, and diagrams cut out as pictures.";
  else if (convState.target === "searchable-pdf") hint = "Adds an invisible text layer to scanned PDFs and photos so you can search, select and copy the text.";
  else if (convState.target === "png") hint = "One PNG per page; several pages are saved together as a .zip.";
  $("#conv-hint").textContent = hint;
  $("#conv-go").disabled = !convState.files.length || bad.length > 0 || Boolean(convState.jobId);
}

async function runConvert(files, target) {
  if (convState.jobId) return toast("Please wait for the current conversion to finish.");
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  form.append("target", target);
  if (target === "searchable-pdf" && $("#view-convert").hidden) toast("Making a searchable PDF… it will download when ready.");
  try {
    const job = await api("/api/convert", { method: "POST", body: form });
    convState.jobId = job.id;
    convState.autoDownload = !$("#view-ocr").hidden;
    $("#conv-progress").hidden = false;
    renderConvert();
    clearInterval(convState.timer);
    convState.timer = setInterval(async () => {
      try { renderConvertJob(await api(`/api/jobs/${convState.jobId}`)); } catch { /* retry */ }
    }, 700);
  } catch (e) { toast(e.message); }
}

function renderConvertJob(job) {
  $("#conv-cancel").hidden = job.state !== "running";
  $("#conv-msg").textContent = job.state === "error" ? job.error : `${job.message} · ${timeText(job)}`;
  $("#conv-fill").style.width = `${Math.max(3, Math.round(((job.done + (job.state === "done" ? 1 : 0)) / Math.max(job.total, 1)) * 100))}%`;
  if (job.state === "running") return;
  clearInterval(convState.timer);
  convState.jobId = null;
  $("#conv-progress").hidden = true;
  renderConvert();
  if (job.state === "error") return toast(job.error);
  const results = job.result || [];
  job.log.filter((m) => m.startsWith("⚠")).forEach((m) => toast(m.slice(2)));
  if (convState.autoDownload) {
    results.forEach((r) => el("a", { href: r.url, download: r.name }).click());
    return;
  }
  loadConverted();
  toast(`Converted ${plural(results.length, "file")}.`);
}

async function loadConverted() {
  const files = await api("/api/converted").catch(() => []);
  $("#conv-results").hidden = !files.length;
  $("#conv-list").replaceChildren(...files.map((r) => el("li", {},
    el("span", { class: `file-icon ${ext(r.name).slice(1)}` }, ext(r.name).slice(1, 5)),
    el("div", { class: "item-main" }, el("div", { class: "item-name" }, r.name),
      el("div", { class: "item-sub" }, `${Math.max(1, Math.round(r.size / 1024))} KB · ${new Date(r.created * 1000).toLocaleString()}`)),
    el("a", { class: "btn small primary", href: r.url, download: r.name }, "Download"),
    el("button", { class: "btn small ghost", type: "button", "aria-label": `Delete ${r.name}`, onclick: async () => {
      await api(r.url, { method: "DELETE" }).catch((e) => toast(e.message));
      loadConverted();
    } }, "Delete"))));
}

async function deleteAllConverted() {
  if (!confirm("Delete all converted files?")) return;
  const r = await api("/api/converted", { method: "DELETE" }).catch((e) => toast(e.message));
  if (r) toast(`Deleted ${plural(r.removed, "file")}.`);
  loadConverted();
}

async function deleteAllData() {
  const settings = $("#wipe-settings").checked;
  const answer = prompt("This deletes all your uploaded files, exams, study sets, converted files, the question bank and analyses"
    + (settings ? ", plus your AI settings and API keys" : "") + ". It can't be undone.\n\nType DELETE to confirm.");
  if (answer === null) return;
  if (answer.trim().toUpperCase() !== "DELETE") return toast("Nothing was deleted.");
  try {
    await api("/api/data/delete-all", { json: { confirm: "DELETE", settings } });
  } catch (e) { return toast(e.message); }
  try {
    Object.keys(localStorage).filter((k) => k.startsWith("sgpt:") && (settings || k !== "sgpt:ai")).forEach((k) => localStorage.removeItem(k));
  } catch { /* storage blocked */ }
  toast("All data deleted.");
  setTimeout(() => location.reload(), 800);
}

// ---------- Download (video / audio), cobalt-style -------------------------------------
const mediaState = { jobId: null, timer: null, tab: "video" };
const MEDIA_LANGS = [["en", "English"], ["zh", "中文"], ["ms", "Bahasa Melayu"], ["ta", "தமிழ்"], ["hi", "हिन्दी"],
  ["ja", "日本語"], ["ko", "한국어"], ["id", "Bahasa Indonesia"], ["es", "Español"], ["fr", "Français"], ["de", "Deutsch"],
  ["ar", "العربية"], ["pt", "Português"], ["ru", "Русский"]];
const MODE_HINTS = { auto: "Video with sound.", audio: "Only the sound, e.g. as MP3.", mute: "Video without sound." };

function mediaSettings() { return { ...state.meta.media.defaults, ...store.get("media", {}) }; }
function setMediaSetting(key, value) { store.set("media", { ...store.get("media", {}), [key]: value }); renderMediaSettings(); }

function mediaSpec() {
  const s = mediaSettings();
  return {
    video: [
      { key: "quality", title: "video quality", options: state.meta.media.qualities,
        desc: "if preferred video quality isn't available, next best is picked instead." },
      { key: "codec", title: "preferred youtube video codec", options: [["h264", "h264 (mp4)"], ["av1", "av1 (webm)"], ["vp9", "vp9 (webm)"]],
        desc: { h264: "h264: best compatibility, average quality. max quality is 1080p.",
          av1: "av1: best quality, small file size. most supported resolutions.",
          vp9: "vp9: same quality as av1, but the file is about 2x bigger. most supported resolutions." }[s.codec] },
      { key: "container", title: "file container", options: [["auto", "auto"], ["mp4", "mp4"], ["webm", "webm"], ["mkv", "mkv"]],
        desc: "when \"auto\" is selected, the best container is picked automatically for the chosen codec." },
      { key: "allow_h265", title: "high efficiency video codec", toggle: "allow h265 for videos",
        desc: "allows downloading videos from platforms like tiktok in higher quality at cost of compatibility." },
      { key: "twitter_gif", title: "twitter/x", toggle: "convert looping videos to GIF",
        desc: "GIF conversion is inefficient, converted file may be big and low quality." },
    ],
    audio: [
      { key: "audio_format", title: "audio format", options: ["best", "mp3", "ogg", "wav", "opus"].map((f) => [f, f]),
        desc: "all formats but \"best\" are converted from the source format, there will be some quality loss." },
      { key: "bitrate", title: "audio bitrate", options: ["320", "256", "128", "96", "64", "8"].map((b) => [b, `${b}kb/s`]),
        desc: "bitrate is applied only when converting audio to a lossy format (mp3, ogg, opus)." },
      { key: "dub", title: "youtube audio track", select: [["original", "original"], ...MEDIA_LANGS],
        desc: "a dubbed audio track in this language is used if the video has one." },
    ],
    other: [
      { key: "subtitles", title: "subtitles", select: [["none", "none"], ["auto", "all available"], ...MEDIA_LANGS],
        desc: "subtitles in this language are added to the video file if they're available." },
      { key: "filename", title: "filename style", options: ["classic", "basic", "pretty", "nerdy"].map((f) => [f, f]),
        desc: { classic: "youtube_dQw4w9WgXcQ_1920x1080_h264.mp4", basic: "Video Title (1080p, h264).mp4",
          pretty: "Video Title (1080p, h264, youtube).mp4", nerdy: "Video Title (1080p, h264, youtube, dQw4w9WgXcQ).mp4" }[s.filename] },
      { key: "no_metadata", title: "file metadata", toggle: "disable file metadata",
        desc: "title, artist, and other info will not be added to the file." },
      { key: "cookies", title: "sign-in cookies", select: state.meta.media.browsers.map((b) => [b, b === "none" ? "don't use" : b]),
        desc: "for videos that need you to be signed in (Instagram, Facebook, age-restricted YouTube): sign in to the site in this browser. Cookies are read on this computer only and never sent anywhere else. Firefox works best." },
    ],
  };
}

function renderMediaSettings() {
  const s = mediaSettings();
  $$("[data-media-tab]").forEach((t) => t.classList.toggle("active", t.dataset.mediaTab === mediaState.tab));
  $("#media-settings-body").replaceChildren(...mediaSpec()[mediaState.tab].map((row) => el("div", { class: "media-setting" },
    el("h3", {}, row.title),
    row.options && el("div", { class: "segmented wrap-auto", role: "radiogroup", "aria-label": row.title },
      row.options.map(([value, label]) => el("label", {},
        el("input", { type: "radio", name: `media-${row.key}`, value, checked: String(s[row.key]) === value,
          onchange: () => setMediaSetting(row.key, value) }), el("span", {}, label)))),
    row.select && el("select", { "aria-label": row.title, onchange: (e) => setMediaSetting(row.key, e.target.value) },
      row.select.map(([value, label]) => el("option", { value, selected: s[row.key] === value }, label))),
    row.toggle && el("label", { class: "check" }, el("input", { type: "checkbox", checked: Boolean(s[row.key]),
      onchange: (e) => setMediaSetting(row.key, e.target.checked) }), row.toggle),
    el("p", { class: "hint" }, row.desc))));
}

function mediaMode() { return $("input[name=media-mode]:checked").value; }

function renderMediaPage() {
  const m = state.meta.media;
  $("#media-missing").hidden = m.available;
  $("#media-sites").textContent = m.sites.join(" · ") + " · and many more";
  $("#media-mode-hint").textContent = MODE_HINTS[mediaMode()];
  $("#media-clear").hidden = !$("#media-url").value;
  $("#media-go").disabled = !m.available || Boolean(mediaState.jobId);
  renderMediaSettings();
  loadDownloads();
}

async function startMediaDownload() {
  const url = $("#media-url").value.trim();
  if (!/^https?:\/\/\S+$/.test(url)) return toast("Paste a link that starts with http:// or https://");
  if (mediaState.jobId) return toast("Please wait for the current download to finish.");
  store.set("mediaMode", mediaMode());
  let job;
  try { job = await api("/api/media/download", { json: { url, settings: { ...mediaSettings(), mode: mediaMode() } } }); }
  catch (e) { return toast(e.message); }
  mediaState.jobId = job.id;
  $("#media-progress").hidden = false;
  $("#media-thumb").hidden = true;
  $("#media-title").textContent = "Getting ready…";
  renderMediaPage();
  clearInterval(mediaState.timer);
  mediaState.timer = setInterval(async () => {
    try { renderMediaJob(await api(`/api/jobs/${mediaState.jobId}`)); } catch { /* retry */ }
  }, 700);
}

function renderMediaJob(job) {
  const meta = job.result?.meta || {};
  if (meta.title) $("#media-title").textContent = meta.title + (meta.uploader ? ` · ${meta.uploader}` : "");
  if (meta.thumbnail && $("#media-thumb").src !== meta.thumbnail) { $("#media-thumb").src = meta.thumbnail; $("#media-thumb").hidden = false; }
  $("#media-msg").textContent = job.state === "error" ? job.error : job.message;
  $("#media-time").textContent = timeText(job);
  $("#media-fill").style.width = `${Math.max(3, Math.round((job.done / Math.max(job.total, 1)) * 100))}%`;
  $("#media-cancel").hidden = job.state !== "running";
  if (job.state === "running") return;
  clearInterval(mediaState.timer);
  mediaState.jobId = null;
  renderMediaPage();
  if (job.state === "error") return toast(job.error);
  $("#media-progress").hidden = true;
  if (job.state === "cancelled") return toast("Download stopped.");
  const file = job.result?.file;
  if (file) { el("a", { href: file.url, download: file.name }).click(); toast(`Saved ${file.name}`); }
}

async function loadDownloads() {
  const files = await api("/api/downloads").catch(() => []);
  $("#media-results").hidden = !files.length;
  $("#media-list").replaceChildren(...files.map((r) => el("li", {},
    el("span", { class: `file-icon media ${ext(r.name).slice(1)}` }, ext(r.name).slice(1, 5)),
    el("div", { class: "item-main" }, el("div", { class: "item-name", title: r.name }, r.name),
      el("div", { class: "item-sub" }, `${r.size > 1048576 ? (r.size / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(r.size / 1024)) + " KB"} · ${new Date(r.created * 1000).toLocaleString()}`)),
    el("a", { class: "btn small primary", href: r.url, download: r.name }, "Save"),
    el("button", { class: "btn small ghost", type: "button", "aria-label": `Delete ${r.name}`, onclick: async () => {
      await api(r.url, { method: "DELETE" }).catch((e) => toast(e.message));
      loadDownloads();
    } }, "Delete"))));
}

async function deleteAllDownloads() {
  if (!confirm("Delete all downloaded files?")) return;
  const r = await api("/api/downloads", { method: "DELETE" }).catch((e) => toast(e.message));
  if (r) toast(`Deleted ${plural(r.removed, "file")}.`);
  loadDownloads();
}

async function useSubtitles() {
  const url = $("#media-url").value.trim();
  if (!/^https?:\/\/\S+$/.test(url)) return toast("Paste the video's link first.");
  let job;
  try { job = await api("/api/media/transcript", { json: { url, language: $("#language").value || "en" } }); }
  catch (e) { return toast(e.message); }
  toast("Getting the subtitles…");
  const timer = setInterval(async () => {
    let j;
    try { j = await api(`/api/jobs/${job.id}`); } catch { return; }
    if (j.state === "running") return;
    clearInterval(timer);
    if (j.state !== "done") return toast(j.error || "Stopped.");
    await loadLibrary();
    toast(`Added “${j.result.name}” to your sources. Use it on the Exam or Study page.`);
  }, 800);
}

function initMedia() {
  $("#media-go").addEventListener("click", startMediaDownload);
  $("#media-url").addEventListener("keydown", (e) => { if (e.key === "Enter") startMediaDownload(); });
  $("#media-url").addEventListener("input", () => { $("#media-clear").hidden = !$("#media-url").value; });
  $("#media-clear").addEventListener("click", () => { $("#media-url").value = ""; $("#media-clear").hidden = true; $("#media-url").focus(); });
  $("#media-paste").addEventListener("click", async () => {
    try { $("#media-url").value = (await navigator.clipboard.readText()).trim(); $("#media-clear").hidden = !$("#media-url").value; }
    catch { toast("Your browser blocked pasting. Press Ctrl+V in the box instead."); $("#media-url").focus(); }
  });
  const mode = store.get("mediaMode", "auto");
  const radio = $(`input[name=media-mode][value=${mode}]`);
  if (radio) radio.checked = true;
  $$("input[name=media-mode]").forEach((r) => r.addEventListener("change", () => { store.set("mediaMode", r.value); renderMediaPage(); }));
  $$("[data-media-tab]").forEach((t) => t.addEventListener("click", () => { mediaState.tab = t.dataset.mediaTab; renderMediaSettings(); }));
  $("#media-cancel").addEventListener("click", () => mediaState.jobId && stopJob(mediaState.jobId));
  $("#media-clear-all").addEventListener("click", deleteAllDownloads);
  $("#media-subs").addEventListener("click", useSubtitles);
}

// ---------- Jobs on other pages: progress, time left and Stop ---------------------------
const JOB_PAGES = { generate: "create", analyse: "create", regenerate: "create", bank: "bank", "bank-solve": "bank",
  study: "study", ask: "study", ocr: "ocr", convert: "convert", media: "media", transcript: "media" };
const JOB_NAMES = { generate: "Writing your exam", analyse: "Analysing past papers", regenerate: "Rewriting a question",
  bank: "Sorting the question bank", "bank-solve": "Answering bank questions", study: "Making study material",
  ask: "Answering your question", ocr: "OCR", convert: "Converting files", media: "Downloading",
  transcript: "Getting subtitles" };
const dock = { timer: null };

function currentView() { return $(".nav-link.active")?.dataset.view; }

async function stopJob(id) {
  await api(`/api/jobs/${id}/cancel`, { method: "POST" }).catch(() => {});
  toast("Stopping after the current step…");
}

async function pollDock() {
  let jobs = [];
  try { jobs = await api("/api/jobs/running"); } catch { /* server restarting */ }
  // Jobs on another page, plus the two that have no Stop button on their own page.
  const away = jobs.filter((j) => JOB_PAGES[j.kind] !== currentView() || j.kind === "regenerate" || j.kind === "ask");
  $("#job-dock").replaceChildren(...away.map((j) => el("div", { class: "job-card" },
    el("div", { class: "job-top" },
      el("button", { class: "job-name", type: "button", title: "Go to this page", onclick: () => showView(JOB_PAGES[j.kind]) }, JOB_NAMES[j.kind] || j.kind),
      el("button", { class: "btn small", type: "button", onclick: () => stopJob(j.id) }, "Stop")),
    el("div", { class: "job-msg", title: j.message }, j.message),
    el("div", { class: "bar" }, el("div", { style: `width:${Math.max(3, Math.round((j.done / Math.max(j.total, 1)) * 100))}%` })),
    el("div", { class: "job-msg" }, timeText(j)))));
  clearTimeout(dock.timer);
  dock.timer = setTimeout(pollDock, jobs.length ? 1500 : 6000);
}

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  el("a", { href: url, download: name }).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderOcrResults() {
  $("#ocr-results").replaceChildren(...ocrState.results.map((file, fi) => {
    const base = file.name.replace(/\.[^.]+$/, "");
    const ocrPages = file.pages.filter((p) => p.method === "ocr").length;
    return el("article", { class: "ocr-file" },
      el("div", { class: "ocr-file-head" },
        el("div", {}, el("h3", {}, file.name),
          el("div", { class: "muted", style: "font-size:13px" },
            `${plural(file.pages.length, "page")} · ${ocrPages} read with OCR · ${file.pages.reduce((a, p) => a + p.text.length, 0).toLocaleString()} characters`)),
        el("div", { class: "actions" },
          el("button", { class: "btn small", type: "button", onclick: async () => {
            try { await navigator.clipboard.writeText(ocrText(file)); toast("Copied."); } catch { toast("Copy failed. Use a download instead."); }
          } }, "Copy"),
          ocrState.files[file.name] && el("span", { class: "btn-group", title: "Same look as the original" },
            el("span", { class: "group-label" }, "Same look:"),
            el("button", { class: "btn small", type: "button",
              title: "Editable Word file laid out like the original: text in the same place and size, diagrams as pictures",
              onclick: () => runConvert([ocrState.files[file.name]], "docx") }, "Word"),
            el("button", { class: "btn small", type: "button",
              title: "The original pages with a hidden text layer, so you can search, select and copy the text",
              onclick: () => runConvert([ocrState.files[file.name]], "searchable-pdf") }, "PDF")),
          el("span", { class: "btn-group", title: "Just the text, including your edits below" },
            el("span", { class: "group-label" }, "Text only:"),
            ...[["docx", "Word"], ["txt", ".txt"], ["md", ".md"]].map(([fmt, label]) => el("button", { class: "btn small", type: "button",
              onclick: () => exportText(ocrMarkdown(file), fmt, base) }, label))),
          el("button", { class: "btn small primary", type: "button", title: "Add this text to your exam sources", onclick: async () => {
            const form = new FormData();
            form.append("files", new File([ocrText(file)], `${base} (OCR).txt`, { type: "text/plain" }));
            try { await api("/api/library", { method: "POST", body: form }); await loadLibrary(); toast("Added to your exam sources."); }
            catch (e) { toast(e.message); }
          } }, "Use as exam source"),
          el("button", { class: "icon-btn", type: "button", "aria-label": "Remove result", onclick: () => { ocrState.results.splice(fi, 1); renderOcrResults(); } }, "✕"))),
      ...file.pages.map((p) => el("section", { class: "ocr-page" },
        el("div", { class: "ocr-page-head" }, `Page ${p.page}`,
          el("span", { class: "tag" }, p.method === "ocr" ? "OCR" : "Selectable text")),
        el("textarea", { rows: Math.min(18, Math.max(5, p.text.split("\n").length + 1)), "aria-label": `Text of page ${p.page}`,
          oninput: (e) => (p.text = e.target.value) }, p.text))));
  }));
}

// ---------- Wiring ---------------------------------------------------------------------
function wire() {
  $$(".nav-link").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  $("#bank-cancel").addEventListener("click", () => bankState.jobId && stopJob(bankState.jobId));
  $("#conv-cancel").addEventListener("click", () => convState.jobId && stopJob(convState.jobId));
  $("#conv-clear").addEventListener("click", deleteAllConverted);
  $("#wipe-all").addEventListener("click", deleteAllData);
  initMedia();
  pollDock();
  $$("[data-view-link]").forEach((b) => b.addEventListener("click", () => {
    showView(b.dataset.viewLink);
    if (!state.jobId) showStage("empty");
  }));

  const drop = $("#dropzone");
  $("#file-input").addEventListener("change", (e) => { uploadFiles(e.target.files); e.target.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));

  $$("[data-src]").forEach((tab) => tab.matches(".tab") && tab.addEventListener("click", () => {
    $$(".tab[data-src]").forEach((t) => t.classList.toggle("active", t === tab));
    $$(".src-pane").forEach((p) => (p.hidden = p.dataset.src !== tab.dataset.src));
  }));

  const builder = $(".builder");
  $$("#mix-custom input").forEach((input) => input.addEventListener("input", () => {
    state.mix[input.dataset.level] = Number(input.value);
  }));
  builder.addEventListener("input", () => { saveBuilder(); updateSources(); renderDifficulty(); });
  builder.addEventListener("change", () => { saveBuilder(); updateSources(); renderDifficulty(); });

  const ocrDrop = $("#ocr-drop");
  $("#ocr-input").addEventListener("change", (e) => { startOcr(e.target.files); e.target.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => ocrDrop.addEventListener(ev, (e) => { e.preventDefault(); ocrDrop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => ocrDrop.addEventListener(ev, (e) => { e.preventDefault(); ocrDrop.classList.remove("drag"); }));
  ocrDrop.addEventListener("drop", (e) => startOcr(e.dataTransfer.files));
  $("#ocr-cancel").addEventListener("click", () => ocrState.jobId && api(`/api/jobs/${ocrState.jobId}/cancel`, { method: "POST" }).catch(() => {}));

  const convDrop = $("#conv-drop");
  const addConvFiles = (files) => { convState.files.push(...files); renderConvert(); };
  $("#conv-input").addEventListener("change", (e) => { addConvFiles([...e.target.files]); e.target.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => convDrop.addEventListener(ev, (e) => { e.preventDefault(); convDrop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => convDrop.addEventListener(ev, (e) => { e.preventDefault(); convDrop.classList.remove("drag"); }));
  convDrop.addEventListener("drop", (e) => addConvFiles([...e.dataTransfer.files]));
  $("#conv-go").addEventListener("click", () => runConvert(convState.files, convState.target));

  $("#bank-language").append(...state.meta.languages.map((l) => el("option", { value: l.id }, l.label)));
  $("#bank-language").value = store.get("bankLanguage", $("#language").value || "en");
  $("#bank-language").addEventListener("input", (e) => store.set("bankLanguage", e.target.value));
  $("#bank-build").addEventListener("click", () => runBankJob("/api/bank/build", { subject: $("#subject").value, language: $("#bank-language").value }));
  $("#bank-answers").addEventListener("click", () => {
    const ids = bankVisible().flatMap(([, qs]) => qs).filter((q) => !q.answer).map((q) => q.id).slice(0, 60);
    if (!ids.length) return toast("These questions already have answers.");
    if (ids.length > 20 && !confirm(`Write and double-check answers for ${ids.length} questions? This can take a while.`)) return;
    runBankJob("/api/bank/solve", { ids, language: $("#bank-language").value });
  });
  $$("[data-bank-tab]").forEach((t) => t.addEventListener("click", () => { bankState.tab = t.dataset.bankTab; renderBank(); }));
  ["bank-search", "bank-sort", "bank-n"].forEach((id) => $("#" + id).addEventListener("input", renderBank));
  $("#bank-view").value = store.get("bankView", "pictures");
  bankState.textOnly = $("#bank-view").value === "text";
  $("#bank-view").addEventListener("input", (e) => {
    bankState.textOnly = e.target.value === "text";
    store.set("bankView", e.target.value);
    renderBank();
  });
  $("#bank-chapter").addEventListener("change", (e) => { bankState.chapter = e.target.value; renderBank(); });
  const bankMenu = $("#bank-export");
  $("#bank-export-btn").addEventListener("click", (e) => { e.stopPropagation(); bankMenu.hidden = !bankMenu.hidden; });
  document.addEventListener("click", () => (bankMenu.hidden = true));

  $("#generate").addEventListener("click", startGeneration);
  $("#cancel").addEventListener("click", async () => {
    if (!state.jobId) return;
    $("#progress-msg").textContent = "Stopping after the current step…";
    await api(`/api/jobs/${state.jobId}/cancel`, { method: "POST" }).catch(() => {});
  });

  $$(".result .tab").forEach((t) => t.addEventListener("click", () => { state.tab = t.dataset.tab; renderExam(); }));
  const title = $("#exam-title");
  title.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); title.blur(); } });
  title.addEventListener("blur", async () => {
    const value = title.textContent.trim();
    if (!state.exam || !value || value === state.exam.title) { title.textContent = state.exam?.title || ""; return; }
    try { state.exam = await api(`/api/exams/${state.exam.id}`, { method: "PATCH", json: { title: value } }); renderExam(); loadExams(); }
    catch (e) { toast(e.message); }
  });

  const menu = $("#export-menu");
  $("#export-btn").addEventListener("click", (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; });
  document.addEventListener("click", () => (menu.hidden = true));
  $("#copy").addEventListener("click", async () => {
    try {
      const res = await fetch(`/api/exams/${state.exam.id}/export?part=all`);
      await navigator.clipboard.writeText(await res.text());
      toast("Copied as Markdown.");
    } catch { toast("Copy failed. Use an export instead."); }
  });
  $("#print").addEventListener("click", () => {
    if (state.tab === "questions") { state.tab = "paper"; renderExam(); }
    setTimeout(() => window.print(), 50);
  });
}

async function init() {
  try { state.meta = await api("/api/meta"); }
  catch { document.body.prepend(el("p", { class: "note warn" }, "Could not reach the SGPT server. Is it still running?")); return; }
  $("#provider").replaceChildren(...state.meta.providers.map((p) => el("option", { value: p.id }, p.label)));
  $("#language").replaceChildren(...state.meta.languages.map((l) => el("option", { value: l.id }, l.label)));

  $("#engine").replaceChildren(...state.meta.search.engines.map((e) => el("option", { value: e.id }, e.label)));
  $("#ocr-missing").hidden = Boolean(state.meta.ocr);
  loadBuilder();
  wire();
  wireSettings();
  renderSettings();
  renderPlan();
  renderDifficulty();
  renderConvert();
  initStudy();
  await Promise.all([loadLibrary(), loadExams(), checkStatus()]);
  // Pick up an exam or analysis that was already running (e.g. after a page refresh).
  api("/api/jobs/current").then((job) => job && ["generate", "analyse"].includes(job.kind) && followJob(job)).catch(() => {});
}

init();
