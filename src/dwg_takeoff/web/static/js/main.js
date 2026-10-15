// Startup and drawing selection: health check, upload, project switching. Entry point.

import { $, S, api, esc, toast } from "./core.js";
import { loadInfo, renderSuggestions, saveNotes, uploadReference } from "./info.js";
import { renderUnitsBanner } from "./units.js";
import { applyRotation, clearGroup, fit, loadView, setupViewer, viewerMsg } from "./viewer.js";
import { drawRuler, setRuler } from "./ruler.js";
import { ask, cancelJob, checkReuse, loadLatestRun } from "./ask.js";
import { renderExplorer } from "./explorer.js";
import { loadRuns } from "./history.js";

async function init() {
  bindUi();
  setupViewer();
  try {
    const h = await api("/api/health");
    S.health = h;
    $("statusChips").innerHTML =
      `<span class="chip ${h.converter_ok ? "ok" : "bad"}" title="${esc(h.converter_ok ? "Convertor DWG → DXF" : h.converter_hint)}"><span class="dot"></span>ODA</span>` +
      h.backends.map((b) => `<span class="chip ${b.available ? "ok" : "bad"}" title="${esc(b.detail)}"><span class="dot"></span>${esc(b.name === "codex" ? "Codex" : b.name === "anthropic" ? "Claude API" : "OpenAI API")}</span>`).join("");
    const saved = store("backend");
    const sel = $("backend");
    sel.innerHTML = h.backends.map((b) => `<option value="${b.name}" ${b.available ? "" : "disabled"} title="${esc(b.detail)}">${esc(b.label)}${b.available ? "" : " — neconfigurat"}</option>`).join("");
    const pick = h.backends.find((b) => b.name === saved && b.available) || h.backends.find((b) => b.default && b.available) || h.backends.find((b) => b.available);
    if (pick) sel.value = pick.name;
    const eff = store("effort");
    if (eff) $("effort").value = eff;
  } catch (_) { /* ignore */ }
  await loadProjects();
}

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem("dwgtakeoff." + key);
    localStorage.setItem("dwgtakeoff." + key, value);
  } catch (_) { return null; }
  return null;
}

function bindUi() {
  $("backend").addEventListener("change", (e) => store("backend", e.target.value));
  $("effort").addEventListener("change", (e) => store("effort", e.target.value));
  $("cancelBtn").addEventListener("click", cancelJob);
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $("projectSelect").addEventListener("change", (e) => selectProject(e.target.value));
  $("uploadInput").addEventListener("change", upload);
  $("askBtn").addEventListener("click", ask);
  $("query").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(); });
  $("query").addEventListener("input", () => { clearTimeout(S.reuseT); S.reuseT = setTimeout(checkReuse, 250); });
  $("fitBtn").addEventListener("click", () => fit());
  $("rotateBtn").addEventListener("click", () => { S.rotate = !S.rotate; applyRotation(); fit(); });
  // one opacity for the background and its deep-zoom tiles (stacked translucent layers would darken)
  $("bgOpacity").addEventListener("input", (e) => ($("bgLayer").style.opacity = e.target.value));
  $("rulerBtn").addEventListener("click", () => setRuler(!S.ruler));
  $("helpBtn").addEventListener("click", () => $("helpDlg").showModal());
  $("projectNotes").addEventListener("input", () => { $("notesState").textContent = "…"; clearTimeout(S.notesT); S.notesT = setTimeout(saveNotes, 700); });
  $("refInput").addEventListener("change", uploadReference);
  setupDrop();
  // tabs: arrow keys move between them (ARIA tab pattern)
  $("tabs").addEventListener("keydown", (e) => {
    const tabs = [...document.querySelectorAll(".tab")];
    const i = tabs.findIndex((t) => t.classList.contains("active"));
    const j = e.key === "ArrowRight" ? (i + 1) % tabs.length : e.key === "ArrowLeft" ? (i + tabs.length - 1) % tabs.length : -1;
    if (j >= 0) { e.preventDefault(); switchTab(tabs[j].dataset.tab); tabs[j].focus(); }
  });
  window.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.ruler) { S.rulerPts = []; S.rulerClosed = false; drawRuler(); } });
  $("bgLayer").style.opacity = $("bgOpacity").value;
}

export function switchTab(name) {
  document.querySelectorAll(".tab").forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll(".tab-panel").forEach((p) => (p.hidden = p.id !== `tab-${name}`));
  if (name === "history") loadRuns();
}

async function loadProjects(selectId) {
  S.projects = await api("/api/projects");
  const sel = $("projectSelect");
  sel.innerHTML = S.projects.map((p) => `<option value="${p.id}">${esc(p.name)}${p.status !== "ready" ? " (" + p.status + "…)" : ""}</option>`).join("");
  const fromUrl = (/[#&]p=([0-9a-f]+)/.exec(location.hash) || [])[1];  // deep link: #p=<drawing id>
  const known = (id) => id && S.projects.some((p) => p.id === id);
  const target = selectId || S.pid || (known(fromUrl) && fromUrl) || (S.projects[0] && S.projects[0].id);
  if (target) { sel.value = target; await selectProject(target); }
  else viewerMsg("Încarcă un fișier .dwg pentru a începe.");
}

async function upload(e) {
  const f = e.target.files[0];
  e.target.value = "";
  if (f) await uploadFile(f);
}

// upload with a progress bar (XHR: fetch has no upload progress)
function uploadFile(f) {
  if (!/\.(dwg|dxf)$/i.test(f.name)) { toast("Se acceptă doar fișiere .dwg sau .dxf.", 4000); return Promise.resolve(); }
  const bar = $("uploadBar"), fill = $("uploadFill");
  bar.hidden = false; fill.style.width = "0%";
  $("uploadLabel").textContent = `Se încarcă ${f.name}…`;
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/projects");
    xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) fill.style.width = `${(100 * ev.loaded / ev.total).toFixed(0)}%`; };
    xhr.onload = async () => {
      bar.hidden = true;
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) { toast(`${f.name} încărcat — se procesează…`); await loadProjects(body.id); }
      else toast("Eroare la încărcare: " + (body.detail || xhr.statusText), 6000);
      resolve();
    };
    xhr.onerror = () => { bar.hidden = true; toast("Eroare de rețea la încărcare.", 6000); resolve(); };
    const fd = new FormData(); fd.append("file", f);
    xhr.send(fd);
  });
}

function setupDrop() {
  const ov = $("dropOverlay");
  let depth = 0;
  const hasFiles = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
  window.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth++; ov.hidden = false; });
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) ov.hidden = true; });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault(); depth = 0; ov.hidden = true;
    const f = e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
}

async function selectProject(pid) {
  const token = (S.selToken = (S.selToken || 0) + 1);
  if (S.pid !== pid) {
    S.result = null; S.plan = null; S.selected = null; S.view = null; S.activeLayer = null; S.vb = null; S.dirty = false;
    $("results").innerHTML = ""; clearGroup("overlays"); clearGroup("featureHl"); clearGroup("layerHl");
    $("bgImage").removeAttribute("href"); $("siteOutline").setAttribute("d", "");
    $("cursorPos").textContent = ""; $("unitsBanner").hidden = true; S.legendOpen = undefined;
    S.viewReady = false; clearGroup("tiles");
  }
  S.pid = pid;
  if (location.hash !== `#p=${pid}`) history.replaceState(null, "", `#p=${pid}`);
  let p;
  try { p = await api(`/api/projects/${pid}`); } catch (err) { viewerMsg("Eroare: " + err.message); return; }
  if (token !== S.selToken) return;
  S.project = p;
  if (p.status !== "ready") {
    viewerMsg(p.status === "error" ? "Eroare la procesare: " + esc(p.error) :
      `Se procesează planșa (${p.status === "converting" ? "conversie DWG → DXF" : p.status === "extracting" ? "extragere geometrie" : "în așteptare"})…`);
    $("explorer").innerHTML = `<p class="muted">Planșa se procesează…</p>`;
    S.catalogue = null;
    if (p.status !== "error") setTimeout(() => S.pid === pid && selectProject(pid), 2000);
    return;
  }
  renderExplorer();
  renderUnitsBanner();
  renderSuggestions();
  loadInfo(pid);
  await loadView();
  if (token !== S.selToken) return;
  if (!S.result) await loadLatestRun(pid, token);
  checkReuse();
}


init();
