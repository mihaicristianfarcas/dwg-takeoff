// Project information the AI reads: notes, client answers, reference documents.

import { $, S, api, esc, num, toast } from "./core.js";
import { switchTab } from "./main.js";

export async function loadInfo(pid) {
  try { renderInfo(await api(`/api/projects/${pid}/info`)); } catch (_) { /* ignore */ }
}
function renderInfo(info) {
  S.info = info;
  if (document.activeElement !== $("projectNotes")) $("projectNotes").value = info.notes || "";
  const docs = info.documents || [];
  $("infoDocs").innerHTML = docs.map((d) => `<span class="src" title="${esc(d.preview || "")}">📄 ${esc(d.name)} <span class="muted">(${num(d.chars, 0)} car.)</span><button class="x" data-rmref="${esc(d.id)}" title="Elimină documentul">×</button></span>`).join("");
  $("infoDocs").querySelectorAll("[data-rmref]").forEach((b) => b.addEventListener("click", async () => {
    renderInfo(await api(`/api/projects/${S.pid}/references/${b.dataset.rmref}`, { method: "DELETE" }));
  }));
  const parts = [];
  if ((info.notes || "").trim()) parts.push("note");
  if (docs.length) parts.push(`${docs.length} document${docs.length > 1 ? "e" : ""}`);
  $("infoSummary").textContent = parts.length ? parts.join(" · ") + " — folosite la următoarea analiză" : "grosimi, specificații, răspunsuri ale clientului";
  $("infoBox").classList.toggle("has-info", parts.length > 0);
}
export async function saveNotes() {
  const pid = S.pid;
  try {
    const info = await api(`/api/projects/${pid}/info`, { method: "PUT", json: { notes: $("projectNotes").value } });
    if (S.pid === pid) { renderInfo(info); $("notesState").textContent = "salvat"; }
  } catch (err) { $("notesState").textContent = "eroare la salvare: " + err.message; }
}
export async function uploadReference(e) {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  $("notesState").textContent = `se citește ${f.name}…`;
  try { renderInfo(await api(`/api/projects/${S.pid}/references`, { method: "POST", body: fd })); $("notesState").textContent = `${f.name} adăugat`; }
  catch (err) { $("notesState").textContent = ""; toast("Eroare: " + err.message, 6000); }
}
// an open question of the AI becomes a line to answer in the project notes
export function answerQuestion(q) {
  const box = $("infoBox"), ta = $("projectNotes");
  box.open = true;
  switchTab("ask");
  ta.value = (ta.value.trim() ? ta.value.trim() + "\n" : "") + `${q} → `;
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);
  ta.scrollIntoView({ block: "center", behavior: "smooth" });
  clearTimeout(S.notesT); S.notesT = setTimeout(saveNotes, 700);
}

// quick additions to the request, in the drawing's own words (its legend)
export function renderSuggestions() {
  const box = $("suggestions"), p = S.project;
  const seen = new Set(), out = [];
  for (const l of (p && p.legends) || []) {
    const label = l.label.replace(/\s+/g, " ").trim();
    const key = label.toLowerCase();
    if (seen.has(key) || label.length > 60 || label.length < 4) continue;
    seen.add(key);
    out.push(l.sample === "hatch" ? `suprafața: ${label}` : l.sample === "line" ? `lungimea: ${label}` : `numărul: ${label}`);
    if (out.length >= 10) break;
  }
  if (!out.length) { box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false;
  const SHOW = 6;
  box.innerHTML = `<span class="small muted">Din legenda planșei:</span>` +
    out.map((t, i) => `<button class="chip-btn" type="button" data-q="${esc(t)}" ${i >= SHOW ? "hidden" : ""}>+ ${esc(t)}</button>`).join("") +
    (out.length > SHOW ? `<button class="btn-link" type="button" id="moreChips">încă ${out.length - SHOW}…</button>` : "");
  if ($("moreChips")) $("moreChips").addEventListener("click", (e) => { box.querySelectorAll(".chip-btn[hidden]").forEach((b) => (b.hidden = false)); e.target.remove(); });
  box.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => {
    const q = $("query");
    q.value = q.value.trim() ? q.value.trim().replace(/[.,;]$/, "") + ", " + b.dataset.q : b.dataset.q;
    q.focus();
  }));
}
