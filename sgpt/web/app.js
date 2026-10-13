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
const BUILDER_FIELDS = ["topic", "subject", "level", "language", "source_language", "src-text", "src-links",
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
    const use = el("label", { class: "switch", title: f.use ? "Used" : "Not used" },
      el("input", { type: "checkbox", checked: f.use, "aria-label": `Use ${f.name}`,
        onchange: (e) => updateFile(f.name, { use: e.target.checked }) }),
      el("span"));
    return el("li", { class: f.use ? "" : "off" },
      el("span", { class: `file-icon ${f.type}` }, f.type),
      el("div", { class: "item-main" }, el("div", { class: "item-name", title: f.name }, f.name), subEl),
      role,
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
  try { followJob(await api("/api/analyse", { json: aiPayload() })); }
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
        p.difficulty && mixBar(p.difficulty), sectionTable(p.sections)))),
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
    language: $("#language").value, source_language: $("#source_language").value,
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

function renderJob(job) {
  if (job.kind === "generate" || job.kind === "analyse") {
    const pct = job.state === "done" ? 100 : Math.round((job.done / Math.max(job.total, 1)) * 100);
    $("#progress").classList.toggle("running", job.state === "running");
    $("#bar-fill").style.width = `${Math.max(pct, 3)}%`;
    $("#progress-steps").textContent = job.total > 1 ? `Step ${Math.min(job.done + 1, job.total)} of ${job.total}` : "";
    $("#elapsed").textContent = formatTime(job.elapsed);
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
  $$(".nav-link").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (view === "library") loadExams();
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
  $("#ocr-msg").textContent = job.state === "error" ? job.error : job.message;
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

// ---------- Convert --------------------------------------------------------------------
const convState = { files: [], target: "pdf", jobId: null, timer: null };
const CONV_TARGETS = [["pdf", "PDF"], ["docx", "Word"], ["txt", "Text"], ["md", "Markdown"], ["html", "Web page"],
  ["png", "Images"], ["merged-pdf", "Merge into one PDF"], ["searchable-pdf", "Searchable PDF (OCR)"]];

function ext(name) { return (name.match(/\.[^.]+$/) || [""])[0].toLowerCase(); }

function renderConvert() {
  const info = state.meta.convert;
  $("#lo-note").textContent = info.libreoffice ? " · Office files via LibreOffice" : "";
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
  else if (office.length && !info.libreoffice) hint = "Old Word, PowerPoint and Excel files need LibreOffice (free) installed: libreoffice.org";
  else if (convState.target === "docx" && convState.files.some((f) => ext(f.name) === ".pdf")) hint = "PDF → Word keeps the layout when the PDF has real text; scans are read with OCR.";
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
  $("#conv-msg").textContent = job.state === "error" ? job.error : job.message;
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
  $("#conv-results").hidden = false;
  $("#conv-list").prepend(...results.map((r) => el("li", {},
    el("span", { class: `file-icon ${ext(r.name).slice(1)}` }, ext(r.name).slice(1, 5)),
    el("div", { class: "item-main" }, el("div", { class: "item-name" }, r.name),
      el("div", { class: "item-sub" }, `${Math.max(1, Math.round(r.size / 1024))} KB`)),
    el("span"),
    el("a", { class: "btn small primary", href: r.url, download: r.name }, "Download"))));
  toast(`Converted ${plural(results.length, "file")}.`);
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
          ...["docx", "pdf", "txt", "md"].map((fmt) => el("button", { class: "btn small", type: "button",
            onclick: () => exportText(ocrMarkdown(file), fmt, base) }, `.${fmt}`)),
          ocrState.files[file.name] && el("button", { class: "btn small", type: "button",
            title: "The original scan with a hidden text layer, so you can search and copy it",
            onclick: () => runConvert([ocrState.files[file.name]], "searchable-pdf") }, "Searchable PDF"),
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
  $("#source_language").append(...state.meta.languages.map((l) => el("option", { value: l.id }, l.label)));
  $("#engine").replaceChildren(...state.meta.search.engines.map((e) => el("option", { value: e.id }, e.label)));
  $("#ocr-missing").hidden = Boolean(state.meta.ocr);
  loadBuilder();
  wire();
  wireSettings();
  renderSettings();
  renderPlan();
  renderDifficulty();
  renderConvert();
  await Promise.all([loadLibrary(), loadExams(), checkStatus()]);
  api("/api/jobs/current").then((job) => job && followJob(job)).catch(() => {});
}

init();
