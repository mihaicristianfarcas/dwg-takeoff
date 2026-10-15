// Drawing units: where they come from, and changing them.

import { $, S, api, esc, toast } from "./core.js";
import { loadView } from "./viewer.js";
import { recompute } from "./ask.js";
import { renderExplorer } from "./explorer.js";

export const UNIT_SRC = { header: "din antetul desenului", inferred: "deduse din desen", default: "presupuse", override: "alese manual" };
export function unitsSelect(id) {
  const p = S.project, ui = p.unit_info || {};
  const opts = Object.entries(p.unit_choices || {}).map(([code, label]) =>
    `<option value="${code}" ${Number(code) === ui.code ? "selected" : ""}>${esc(label)}</option>`).join("");
  const cal = ui.code === -1 ? `<option value="cal" selected disabled>calibrat: ${esc(ui.name)}</option>` : "";
  return `<select id="${id}" class="units-select" aria-label="Unitățile desenului">${cal}${opts}${ui.source === "override" ? `<option value="">↺ unitățile desenului</option>` : ""}</select>`;
}
export function bindUnitsSelect(id) {
  const sel = $(id);
  if (sel) sel.addEventListener("change", () => setUnits(sel.value === "" ? null : Number(sel.value)));
}
export function renderUnitsBanner() {
  const p = S.project, ui = (p && p.unit_info) || {}, b = $("unitsBanner");
  // shown while the units are inferred/assumed/doubtful, and as a reminder after a manual override
  const doubtful = ui.source && (ui.source !== "header" || ui.confidence !== "high");
  if (!p || !doubtful) { b.hidden = true; return; }
  b.hidden = false;
  b.innerHTML = `<span><b>Unități: ${esc(ui.name === "meters" ? "metri" : ui.name)}</b> (${UNIT_SRC[ui.source] || ui.source}) — toate cantitățile depind de ele.
    <span class="muted">${esc((ui.evidence || [])[0] || "")}</span></span> ${unitsSelect("bannerUnits")}
    <button class="btn-link" id="unitsOk" title="Ascunde">OK</button>`;
  bindUnitsSelect("bannerUnits");
  $("unitsOk").addEventListener("click", () => (b.hidden = true));
}
export async function setUnits(code, scale = null) {
  const pid = S.pid;
  try {
    toast("Se recalculează cu noile unități…");
    const project = await api(`/api/projects/${pid}/units`, { json: { code, scale } });
    if (S.pid !== pid) return;
    S.project = project;
    S.vb = null;
    S.catalogue = null;  // re-measured with the new units
    renderExplorer();
    renderUnitsBanner();
    await loadView();
    if (S.pid !== pid) return;
    if (S.plan) await recompute();
    toast("Unitățile au fost schimbate; cantitățile au fost recalculate.");
  } catch (err) { toast("Eroare: " + err.message, 5000); }
}
