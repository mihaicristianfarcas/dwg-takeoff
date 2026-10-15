// Asking for quantities: AI jobs, progress, saving and re-measuring plans.

import { $, S, api, esc, toast } from "./core.js";
import { drawOverlays } from "./viewer.js";
import { renderResults } from "./results.js";
import { loadCatalogue } from "./catalogue.js";
import { fmtRun } from "./history.js";

export async function ask() {
  const q = $("query").value.trim();
  if (!q || !S.pid) return;
  $("askError").hidden = true;
  $("askBtn").disabled = true;
  $("progress").hidden = false;
  $("progressStage").textContent = "Pornire…"; $("progressTime").textContent = ""; $("progressHint").textContent = "";
  $("timeline").innerHTML = ""; $("cancelBtn").hidden = false;
  try {
    const { job } = await api(`/api/projects/${S.pid}/ask`, { json: { query: q, effort: $("effort").value, backend: $("backend").value } });
    S.job = job; S.query = q; S.runs = null; $("reuseHint").hidden = true;
    pollJob(job);
  } catch (err) { showAskError(err.message); }
}

export async function cancelJob() {
  if (!S.job) return;
  $("cancelBtn").hidden = true;
  $("progressStage").textContent = "Se anulează…";
  try { await api(`/api/jobs/${S.job}/cancel`, { method: "POST" }); } catch (_) { /* ignore */ }
}

export const EFFORT_RO = { low: "rapidă", medium: "normală", high: "aprofundată" };
function fmtSec(x) { x = Math.round(x); return x < 60 ? `${x} s` : `${Math.floor(x / 60)} min ${String(x % 60).padStart(2, "0")} s`; }

function renderProgress(j) {
  $("progressStage").textContent = j.status === "running" ? (j.stage || "") : "";
  const typ = j.typical_seconds;
  $("progressTime").textContent = fmtSec(j.elapsed) + (typ ? ` din ~${fmtSec(typ)}` : "");
  const wrap = $("progressBarWrap"), bar = $("progressBar");
  if (typ) {
    wrap.classList.remove("indeterminate");
    // eases towards 95% while waiting; jumps to 100% when the job is done
    const r = j.elapsed / typ;
    const pct = j.status === "done" ? 100 : Math.min(95, r < 1 ? r * 85 : 85 + 10 * (1 - Math.exp(-(r - 1) * 2)));
    bar.style.width = pct.toFixed(1) + "%";
  } else {
    wrap.classList.add("indeterminate");
  }
  $("progressHint").textContent = `${j.backend_label || ""} · analiză ${EFFORT_RO[j.effort] || j.effort}` +
    (typ ? ` · de obicei durează ~${fmtSec(typ)}` : " · prima rulare cu această setare") +
    " · puteți explora planul în timp ce așteptați";
  // timeline
  const items = [];
  const lookups = {};
  let current = null;
  for (const e of j.events || []) {
    if (e.kind === "stage") { current = { type: "stage", text: e.text, detail: e.detail, t: e.t, done: false }; items.push(current); }
    else if (e.kind === "done") {
      if (current && !current.done) { current.done = true; current.doneText = e.text; current.doneDetail = e.detail; current.t2 = e.t; }
      else items.push({ type: "ok", text: e.text, detail: e.detail, t: e.t });
    } else if (e.kind === "lookup") { const it = { type: "lookup", text: e.text, detail: e.detail, t: e.t }; items.push(it); if (e.id) lookups[e.id] = it; }
    else if (e.kind === "lookup_done") { const it = lookups[e.id]; if (it) { it.result = e.text; } }
    else if (e.kind === "thought") items.push({ type: "thought", text: e.text, t: e.t });
    else if (e.kind === "warning") items.push({ type: "warn", text: e.text, detail: e.detail, t: e.t });
    else if (e.kind === "usage") items.push({ type: "usage", text: e.text, t: e.t });
  }
  const running = j.status === "running";
  const html = items.map((it) => {
    let ic, tx;
    if (it.type === "stage") {
      ic = it.done ? '<span class="ic ok">✓</span>' : running ? '<span class="ic run"></span>' : '<span class="ic warn">!</span>';
      tx = `<b>${esc(it.done ? it.doneText || it.text : it.text)}</b>` + ((it.done ? it.doneDetail : it.detail) ? `<div class="sub">${esc(it.done ? it.doneDetail : it.detail)}</div>` : "");
    } else if (it.type === "ok") { ic = '<span class="ic ok">✓</span>'; tx = `<b>${esc(it.text)}</b>${it.detail ? `<div class="sub">${esc(it.detail)}</div>` : ""}`; }
    else if (it.type === "lookup") {
      ic = it.result ? '<span class="ic dot"></span>' : running ? '<span class="ic run"></span>' : '<span class="ic dot"></span>';
      tx = `${esc(it.text)}${it.result ? ` <span class="sub">· ${esc(it.result)}</span>` : ""}${it.detail ? `<div><span class="cmd" title="${esc(it.detail)}">${esc(it.detail)}</span></div>` : ""}`;
    } else if (it.type === "thought") { ic = '<span class="ic ai">AI</span>'; tx = `<span class="thought">„${esc(it.text)}”</span>`; }
    else if (it.type === "warn") { ic = '<span class="ic warn">!</span>'; tx = `${esc(it.text)}${it.detail ? `<div class="sub">${esc(it.detail)}</div>` : ""}`; }
    else { ic = '<span class="ic dot"></span>'; tx = `<span class="sub">${esc(it.text)}</span>`; }
    return `<li>${ic}<div class="tx">${tx}</div><span class="tm">${fmtSec(it.t2 ?? it.t)}</span></li>`;
  }).join("");
  const tl = $("timeline");
  const atBottom = tl.scrollHeight - tl.scrollTop - tl.clientHeight < 30;
  if (tl.innerHTML !== html) { tl.innerHTML = html; if (atBottom) tl.scrollTop = tl.scrollHeight; }
}

async function pollJob(jid) {
  let j;
  try { j = await api(`/api/jobs/${jid}`); } catch (err) { showAskError(err.message); return; }
  if (S.job !== jid) return;
  renderProgress(j);
  if (j.status === "running") { setTimeout(() => pollJob(jid), 1000); return; }
  $("askBtn").disabled = false; $("cancelBtn").hidden = true;
  if (j.status === "cancelled") { $("progress").hidden = true; toast("Analiza a fost anulată."); return; }
  if (j.status === "error") { $("progress").hidden = true; showAskError(j.error); return; }
  setTimeout(() => { if (S.job === jid) $("progress").hidden = true; }, 1500);
  setResult(j.result, true);
}

function showAskError(msg) {
  $("askBtn").disabled = false; $("progress").hidden = true;
  const e = $("askError"); e.textContent = msg; e.hidden = false;
}

export async function saveRun() {
  try {
    const res = await api(`/api/projects/${S.pid}/runs`, { json: { plan: S.plan, query: S.query, parent_run: S.result && S.result.run } });
    S.dirty = false;
    setResult(res);
    toast("Versiune salvată în istoric.");
  } catch (err) { toast("Eroare la salvare: " + err.message, 5000); }
}

export function setResult(res, fresh = false) {
  S.result = res; S.plan = res.plan; S.query = res.query || S.query;
  if (res.run) $("reuseHint").hidden = true;
  if (fresh) {
    S.dirty = false;
    if (S.catalogue && res.run && S.catalogue.run !== res.run) { S.catalogue = null; loadCatalogue(); }  // "used in" info
    // volumes are drawn on the same footprints as the surfaces - keep the map readable
    S.hidden = new Set(res.items.filter((it) => it.unit === "m³").map((it) => it.id));
    S.selected = null;
  }
  renderResults();
  drawOverlays();
}

export async function recompute() {
  const pid = S.pid, plan = S.plan; // the drawing may change while the request runs
  try {
    const res = await api(`/api/projects/${pid}/execute`, { json: { plan, query: S.query } });
    if (S.pid !== pid || S.plan !== plan) return false;
    res.run = S.result && S.result.run;
    if (S.plan && S.plan._meta) res.plan._meta = S.plan._meta;
    S.dirty = true;
    setResult(res);
    toast("Recalculat.");
    return true;
  } catch (err) { toast("Eroare la recalculare: " + err.message, 5000); return false; }
}

// the same request was already analysed on this drawing: offer its result (instant, no AI call)
const normQ = (q) => (q || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/\s+/g, " ").trim();
export async function checkReuse() {
  const box = $("reuseHint");
  const q = normQ($("query").value);
  if (!S.pid || !q) { box.hidden = true; return; }
  if (!S.runs || S.runs.pid !== S.pid) {
    try { S.runs = { pid: S.pid, list: await api(`/api/projects/${S.pid}/runs`) }; } catch (_) { return; }
  }
  const prev = S.runs.list.find((r) => !r.edited && normQ(r.query) === q);
  if (!prev || (S.result && S.result.run === prev.run)) { box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = `Această cerere a fost deja analizată pe ${esc(fmtRun(prev.run))}${prev.seconds ? ` (AI ${prev.seconds} s)` : ""}. <button class="btn-link" id="reuseBtn">Deschide rezultatul (instant)</button>`;
  $("reuseBtn").addEventListener("click", async () => {
    setResult(await api(`/api/projects/${S.pid}/runs/${prev.run}`), true);
    box.hidden = true;
  });
}

export async function loadLatestRun(pid, token) {
  try {
    const runs = await api(`/api/projects/${pid}/runs`);
    if (token !== S.selToken) return;
    if (runs.length) {
      const res = await api(`/api/projects/${pid}/runs/${runs[0].run}`);
      if (token === S.selToken && !S.result) { setResult(res, true); if (res.query) $("query").value = res.query; }
      S.runs = { pid, list: runs };
    }
  } catch (err) { console.warn("loadLatestRun", err); }
}
