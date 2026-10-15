// Drawing explorer: legends, sheets, tables and notes found in the drawing.

import { $, S, esc, num } from "./core.js";
import { UNIT_SRC, bindUnitsSelect, unitsSelect } from "./units.js";
import { loadCatalogue, showLayer, tableHtml } from "./catalogue.js";

export function swatch(color, title) {
  return color ? `<span class="swatch" style="background:${esc(color)}" title="${esc(title || color)}"></span>` : "";
}

export function renderExplorer() {
  const p = S.project, box = $("explorer");
  let h = `<div class="ex-head small muted">${esc(p.name)} · ${esc(p.dwg_version || p.dxf_version || "")} · ${num(p.n_features, 0)} entități · ${p.n_layers} straturi${p.space && p.space !== "Model" ? ` · măsurat pe planșa „${esc(p.space)}”` : ""}</div>
    <div class="ex-units"><span class="kv-title">Unități desen</span> ${unitsSelect("explorerUnits")}
      <span class="small muted">${esc(UNIT_SRC[(p.unit_info || {}).source] || "")}${(p.unit_info || {}).evidence ? " · " + esc(p.unit_info.evidence[0]) : ""}</span></div>`;
  const warns = [...(p.warnings || [])];
  if (p.xrefs_missing && p.xrefs_missing.length) warns.push(`Referințe externe nelegate (conținut indisponibil): ${p.xrefs_missing.join(", ")}`);
  if (warns.length) h += `<div class="note-box small">${warns.map(esc).join("<br>")}</div>`;
  h += `<div class="section-title">Catalogul planșei <span class="muted small" style="text-transform:none;letter-spacing:0">— tot ce se poate măsura, numerotat; denumirile se pot corecta</span></div>
    <div id="catalogue"><p class="small muted">Se încarcă catalogul…</p></div>`;
  if (!p.legends.length) h += `<div class="section-title">Legende</div><p class="small muted">Nicio legendă detectată — elementele se identifică după straturi, hașuri, culori, blocuri și texte.</p>`;
  else {
    h += `<details class="ex-legends"><summary class="section-title">Legende găsite (${p.legends.length})</summary><table class="ltable"><thead><tr><th>Etichetă</th><th>Strat / hașură</th><th>Planșă</th></tr></thead><tbody>`;
    for (const l of p.legends) {
      h += `<tr class="clickable" data-layer="${esc(l.layer)}" tabindex="0"><td>${swatch(l.color)} ${esc(l.label)}</td><td>${esc(l.layer)}${l.pattern ? ` <span class="tag">${esc(l.pattern)}</span>` : ""}${l.block ? ` <span class="tag">${esc(l.block)}</span>` : ""}</td><td class="nowrap">${esc(l.sheet)}</td></tr>`;
    }
    h += `</tbody></table></details>`;
  }
  if (p.tables && p.tables.length) {
    h += `<div class="section-title">Tabele din desen</div>`;
    for (const t of p.tables) {
      h += `<div class="table-card"><b>${esc(t.id)}</b> · ${esc({ xlsx: "Excel încorporat", docx: "Word încorporat", acad_table: "tabel AutoCAD" }[t.kind] || t.kind)} · ${esc(t.title)}`;
      if (t.objects.length) {
        for (const o of t.objects) h += `<div>${esc(o.object)}: ${o.points.length} puncte${o.footprint_area_m2 ? ` · contur ${num(o.footprint_area_m2)} m² · perimetru ${num(o.footprint_perimeter_m)} m` : ""}</div>`;
      } else {
        h += tableHtml(t.rows.slice(0, 15));
      }
      h += `</div>`;
    }
  }
  if (p.text_tables && p.text_tables.length) {
    h += `<div class="section-title">Texte aliniate în tabel (pe planșe)</div>`;
    for (const t of p.text_tables) h += `<div class="table-card"><b>${esc(t.id)}</b> · ${esc(t.sheet)}${tableHtml(t.rows.slice(0, 12))}</div>`;
  }
  if (p.notes && p.notes.length) {
    h += `<div class="section-title">Note de pe planșe</div>` + p.notes.slice(0, 20).map((n) => `<div class="note-box small" style="margin-bottom:6px;white-space:pre-wrap">${esc(n)}</div>`).join("");
  }
  box.innerHTML = h;
  bindUnitsSelect("explorerUnits");
  box.querySelectorAll("tr[data-layer]").forEach((tr) => {
    const go = () => showLayer(tr.dataset.layer, tr, tr.dataset.pattern, tr.dataset.color);
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
  loadCatalogue();
}
