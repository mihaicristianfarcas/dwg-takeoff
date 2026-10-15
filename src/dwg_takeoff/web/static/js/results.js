// The results table, item details with evidence, exports.

import { $, CONF, KIND, MEASURE, S, STATUS, esc, itemColor, num, toast } from "./core.js";
import { answerQuestion } from "./info.js";
import { clearGroup, drawOverlays, el, highlightFeature, polyPath, zoomToGeom } from "./viewer.js";
import { recompute, saveRun } from "./ask.js";
import { swatch } from "./explorer.js";
import { CAT_RO } from "./catalogue.js";
import { fmtRun } from "./history.js";

function reviewBlock(r) {
  let head, cls = "note-box";
  if (r.error) { head = `Verificarea cantităților de către AI nu a putut fi făcută; rezultatele sunt cele ale primei analize. (${r.error.slice(0, 300)})`; cls = "check"; }
  else if (r.rejected) head = "La verificare, AI-ul a propus corecturi care nu se potriveau cu desenul; s-a păstrat prima analiză.";
  else if ((r.changed || []).length) head = `După ce a văzut cantitățile măsurate, AI-ul a corectat ${r.changed.length === 1 ? "un element" : r.changed.length + " elemente"}:`;
  else head = "AI-ul a verificat cantitățile măsurate și a confirmat alegerile.";
  const notes = (r.notes || []).map((n) => `<li>${esc(n)}</li>`).join("");
  return `<div class="section-title">Verificarea AI</div><div class="${cls}">${esc(head)}${notes && !r.error ? `<ul class="plain review-notes">${notes}</ul>` : ""}</div>`;
}

export function renderResults() {
  const res = S.result, box = $("results");
  if (!res) { box.innerHTML = ""; return; }
  const plan = res.plan || {};
  const meta = plan._meta || {};
  const review = meta.review || null;
  const revised = new Set((review && !review.rejected && review.changed) || []);
  let h = "";
  if (plan.summary) h += `<div class="summary">${esc(plan.summary)}</div>`;
  h += `<div class="results-head"><div class="section-title" style="margin:0">Rezultate</div>
        <span class="meta">${meta.seconds ? `AI ${meta.seconds} s` : ""}${res.run ? ` · rulare ${esc(fmtRun(res.run))}` : ""}${meta.project_info_chars ? " · cu informații de proiect" : ""}</span>
        <span class="spacer"></span>
        ${S.dirty ? `<span class="badge assumption_based">modificat</span><button class="btn btn-sm btn-primary" id="saveBtn">Salvează</button>` : ""}
        <button class="btn btn-sm" id="xlsxBtn">Export Excel</button>
        <button class="btn btn-sm" id="copyBtn" title="Copiază tabelul (se lipește direct în Excel)">Copiază</button>
        <button class="btn btn-sm" id="jsonBtn">JSON</button></div>`;
  h += `<table class="qtable"><colgroup><col><col class="c-val"><col class="c-status"></colgroup><thead><tr><th>Element</th><th style="text-align:right">Cantitate</th><th>Status</th></tr></thead><tbody>`;
  res.items.forEach((it, i) => {
    const sel = S.selected === it.id;
    h += `<tr class="item-row ${sel ? "selected" : ""}" data-id="${esc(it.id)}">
      <td><div class="item-name"><span class="swatch" style="background:${itemColor(i)}"></span><div>${esc(it.label)}
        <div class="small muted">${esc(it.request_text || "")}</div></div></div></td>
      <td class="val">${it.value === null ? "—" : num(it.value, it.unit === "buc" ? 0 : 2)}<span class="unit">${esc(it.unit || "")}</span></td>
      <td><span class="badge ${it.status}">${STATUS[it.status] || it.status}</span><br><span class="badge conf">${CONF[it.confidence] || ""}</span>${revised.has(it.id) ? `<br><span class="badge reviewed" title="Corectat de AI după verificarea cantităților măsurate">corectat la verificare</span>` : ""}</td>
    </tr>`;
    if (sel) h += `<tr class="detail"><td colspan="3">${itemDetail(it, i)}</td></tr>`;
  });
  h += `</tbody></table>`;
  if (res.checks && res.checks.length) {
    h += `<div class="section-title">Verificări automate</div><div class="checks">` +
      res.checks.map((c) => `<div class="check">${esc(c.message)}</div>`).join("") + `</div>`;
  }
  if (review) h += reviewBlock(review);
  const notes = plan.general_notes || [], qs = plan.questions_for_user || [];
  if (notes.length) h += `<div class="section-title">Observații</div><div class="checks">` + notes.map((n) => `<div class="note-box">${esc(n)}</div>`).join("") + `</div>`;
  if (qs.length) h += `<div class="section-title">De confirmat cu proiectantul / clientul</div><ul class="plain">` + qs.map((q) => `<li>${esc(q)} <button class="btn-link" data-answer="${esc(q)}">Răspunde</button></li>`).join("") + `</ul>`;
  if (res.run) {
    const base = `/api/projects/${S.pid}/runs/${encodeURIComponent(res.run)}`;
    h += `<div class="section-title">Trasabilitate AI</div><div class="row-actions small">
      <a href="${base}/prompt.txt" target="_blank">prompt trimis</a>
      <a href="${base}/plan.json" target="_blank">plan returnat</a>
      <a href="${base}/features.csv" target="_blank">entități (CSV)</a>
      <a href="${base}/codex.log" target="_blank">jurnal Codex</a>
      ${meta.project_info_chars ? `<a href="${base}/project_info.txt" target="_blank">informații de proiect folosite</a>` : ""}
      ${review && !review.error ? `<a href="${base}/review_report.txt" target="_blank">raport de verificare</a>` : ""}
      ${revised.size ? `<a href="${base}/plan_first.json" target="_blank">plan înainte de verificare</a>` : ""}</div>`;
  }
  box.innerHTML = h;
  box.querySelectorAll("tr.item-row").forEach((tr) => tr.addEventListener("click", () => selectItem(tr.dataset.id, true)));
  $("xlsxBtn").addEventListener("click", exportXlsx);
  if ($("saveBtn")) $("saveBtn").addEventListener("click", saveRun);
  $("jsonBtn").addEventListener("click", exportJson);
  box.querySelectorAll("[data-answer]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); answerQuestion(b.dataset.answer); }));
  $("copyBtn").addEventListener("click", copyTable);
  bindDetail(box);
}

function itemDetail(it, idx) {
  let h = `<div class="detail-box" style="border-color:${itemColor(idx)}">`;
  if (it.formula) h += `<div class="formula" title="formula">${esc(it.formula)}</div>`;
  it.components.forEach((c, ci) => {
    const st = c.stats || {};
    let stats = "";
    if (c.measure === "length") {
      stats = `Desenat brut ${num(st.raw_sum)} m → numărat ${num(c.base_value)} m` +
        (st.coincident_removed ? ` · dubluri suprapuse eliminate ${num(st.coincident_removed)} m` : "") +
        (st.parallel_faces_removed ? ` · fețe paralele/dublate eliminate ${num(st.parallel_faces_removed)} m` : "") +
        (st.excluded_shared ? ` · trasee comune cu alt element excluse ${num(st.excluded_shared)} m` : "") +
        ` · toleranță ${num(st.tolerance)} m`;
    } else if (c.measure === "area" || c.measure === "perimeter") {
      const u = c.measure === "area" ? "m²" : "m";
      if (st.raw_sum !== undefined) stats = `Suma entităților ${num(st.raw_sum)} ${u} → ${c.measure === "area" ? "reuniune" : "perimetrul reuniunii"} ${num(st.union ?? c.base_value)} ${u}` + (st.subtracted ? ` · scăzut ${num(st.subtracted)} m²` : "");
      if (st.table_objects) stats += `${stats ? " · " : ""}${st.table_objects} contur(e) din tabele de trasare`;
    } else if (c.measure === "strip_area") {
      stats = `Benzi desenate cu lățime: ${st.entities} · suma ${num(st.raw_sum)} m² → reuniune ${num(st.union)} m²`;
    } else if (c.measure === "count_groups") {
      stats = `${st.entities} entități grupate în ${st.groups} simboluri (distanța de alipire ${num(st.tolerance)} m) — fiecare grup e încadrat pe plan`;
    } else if (c.measure === "enclosed_area") {
      stats = `${st.lines} linii → ${st.faces} suprafețe închise · contur ${num(st.outline_length)} m · toleranță de închidere ${num(st.tolerance)} m`;
    } else if (c.measure === "count") {
      stats = `Entități găsite ${st.raw_count ?? c.n_entities}`;
    }
    h += `<div class="comp"><div class="comp-title"><span>${esc(c.label)}</span><span class="badge conf">${MEASURE[c.measure] || c.measure}</span>
          <span class="val">${num(c.value, c.unit === "buc" ? 0 : 2)} ${esc(c.unit)}</span></div>
          <div class="formula">${esc(c.formula)}</div>`;
    if (stats) h += `<div class="stats-line">${esc(stats)}</div>`;
    if (c.factors && c.factors.length) {
      h += `<div class="factors">` + c.factors.map((f, fi) => `<div class="factor">
          <span>${esc(f.name)}</span>
          <input type="number" step="0.01" value="${f.value}" data-item="${esc(it.id)}" data-comp="${ci}" data-factor="${fi}">
          <span>${esc(f.unit)}</span>
          <span class="origin ${f.origin}">${{ assumed: "presupus", document: "din documente" }[f.origin] || "din planșă"}</span>
          <span class="note">${esc(f.note || "")}</span></div>`).join("") + `</div>`;
    }
    const pc = planComp(it.id, ci);
    if (pc) {
      h += `<div class="sources"><span class="kv-title">Surse:</span> ` + (pc.sources || []).map((src, si) =>
        `<span class="src" title="${esc(JSON.stringify(src))}">${swatch(src.color)}${esc(srcLabel(src))}<button class="x" data-rm-src="${esc(it.id)}|${ci}|${si}" title="Elimină sursa">×</button></span>`).join("") +
        (c.measure === "length" || c.measure === "enclosed_area" || c.measure === "count_groups" ? ` <label class="small muted">toleranță <input type="number" step="0.05" min="0" class="tol" value="${pc.tolerance_m ?? (c.measure === "enclosed_area" ? 0.05 : 0.3)}" data-tol="${esc(it.id)}|${ci}"> m</label>` : "") +
        ` <button class="btn-link" data-add-factor="${esc(it.id)}|${ci}">+ factor</button></div>`;
    }
    if (c.warnings && c.warnings.length) h += `<ul class="warn-list">${c.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`;
    h += evidenceBlock(c);
    h += `</div>`;
  });
  if (it.reasoning) h += `<div><div class="kv-title">Raționament</div><div class="reasoning">${esc(it.reasoning)}</div></div>`;
  if (it.assumptions && it.assumptions.length) h += `<div><div class="kv-title">Ipoteze</div><ul class="plain">${it.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>`;
  if (it.questions && it.questions.length) h += `<div><div class="kv-title">Întrebări</div><ul class="plain">${it.questions.map((a) => `<li>${esc(a)} <button class="btn-link" data-answer="${esc(a)}">Răspunde</button></li>`).join("")}</ul></div>`;
  if (it.warnings && it.warnings.length) h += `<ul class="warn-list">${it.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`;
  h += `<div class="row-actions"><button class="btn-link" data-rename="${esc(it.id)}">Redenumește</button>
        <button class="btn-link danger" data-rm-item="${esc(it.id)}">Șterge elementul</button></div>`;
  h += `</div>`;
  return h;
}

function planItem(id) { return S.plan && (S.plan.items || []).find((x) => x.id === id); }
function planComp(id, ci) { const it = planItem(id); return it && it.components ? it.components[ci] : null; }
function srcLabel(src) {
  if (src.entry) {  // a catalogue entry: its id and current label
    const e = S.catalogue && S.catalogue.pid === S.pid ? S.catalogue.entries.find((x) => x.key === src.entry_key) : null;
    const name = e ? (e.label || CAT_RO[e.category] || "") : "";
    return `${src.entry}${name ? ` „${name}”` : ""} · ${src.table_object ? `tabel: ${src.table_object}` : (src.layer || src.block || "")}`;
  }
  if (src.table_object) return `tabel: ${src.table_object}`;
  let t = src.layer || "?";
  const k = (src.kinds || []).map((x) => KIND[x] || x).join("/");
  if (k) t += ` [${k}]`;
  if (src.pattern) t += ` ${src.pattern}`;
  if (src.color) t += ` ${src.color}`;
  if (src.block) t += ` bloc ${src.block}`;
  if (src.handles && src.handles.length) t += ` (${src.handles.length} handle)`;
  return t;
}

const EVGEO = [];
function evidenceBlock(c) {
  const ev = c.evidence || [];
  if (!ev.length) return "";
  const unit = c.measure === "count" || c.measure === "count_groups" ? "buc" : c.measure === "enclosed_area" ? "m" : c.base_unit;
  const handles = [...new Set(ev.filter((e) => e.handle).map((e) => e.handle))];
  const MAX_ROWS = 400;
  let rows = ev.slice(0, MAX_ROWS).map((e) => {
    let clickable = e.fid !== null && e.fid !== undefined && !e.geometry;
    let attr = clickable ? `data-fid="${e.fid}"` : "";
    if (!clickable && e.geometry) { EVGEO.push({ geometry: e.geometry, label: `${e.block} · ${e.layer}` }); attr = `data-geo="${EVGEO.length - 1}"`; clickable = true; }
    let pts = "";
    if (e.points) pts = `<div class="muted">${e.points.map((p) => `${esc(p[0])}: N ${p[1]} / E ${p[2]}`).join("<br>")}</div>`;
    return `<tr class="${clickable ? "clickable" : ""} ${e.counted === 0 ? "zero" : ""}" ${attr}>
      <td class="mono">${esc(e.handle || "—")}</td>
      <td class="wrap">${swatch(e.color)}${esc(e.layer)}${e.visible === false ? ' <span class="tag hidden">ascuns</span>' : ""}${e.nested ? ' <span class="tag">în bloc</span>' : ""}
        <div class="ev-sub">${esc(KIND[e.kind] || e.kind)}${e.pattern ? " · " + esc(e.pattern) : ""}${e.block ? " · " + esc(e.block) : ""}${e.note ? ` — <span class="ev-note">${esc(e.note)}</span>` : ""}</div>${pts}</td>
      <td class="num">${num(e.raw)}</td><td class="num">${num(e.counted)}</td></tr>`;
  }).join("");
  if (ev.length > MAX_ROWS) rows += `<tr><td colspan="4" class="muted">… încă ${ev.length - MAX_ROWS} entități (lista completă în Export Excel, foaia „Entități”)</td></tr>`;
  return `<details><summary>${ev.length} entități (${handles.length} handle-uri AutoCAD) — click pe rând pentru localizare</summary>
    <div class="row-actions" style="margin:6px 0"><button class="btn-link" data-lisp="${esc(handles.join(" "))}">Copiază selecția pentru AutoCAD (AutoLISP)</button>
    <button class="btn-link" data-handles="${esc(handles.join(", "))}">Copiază lista de handle-uri</button></div>
    <div class="evidence-wrap"><table class="evidence"><thead><tr><th>Handle</th><th>Strat · tip · observație</th><th>Brut (${esc(unit)})</th><th>Numărat</th></tr></thead>
    <tbody>${rows}</tbody></table></div></details>`;
}

function bindDetail(box) {
  box.querySelectorAll("tr[data-fid]").forEach((tr) => tr.addEventListener("click", (e) => { e.stopPropagation(); highlightFeature(Number(tr.dataset.fid)); }));
  box.querySelectorAll("tr[data-geo]").forEach((tr) => tr.addEventListener("click", (e) => {
    e.stopPropagation();
    const g = EVGEO[Number(tr.dataset.geo)];
    clearGroup("featureHl");
    const grp = $("featureHl");
    if (g.geometry.polygons.length) el("path", { d: polyPath(g.geometry.polygons), class: "hl-feature" }, grp);
    zoomToGeom(g.geometry, 6);
    toast(g.label);
  }));
  box.querySelectorAll("[data-lisp]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    const hs = b.dataset.lisp.split(" ").filter(Boolean).map((h) => `"${h}"`).join(" ");
    const code = `(progn (setq ss (ssadd)) (foreach h '(${hs}) (if (handent h) (ssadd (handent h) ss))) (sssetfirst nil ss) (princ))`;
    navigator.clipboard.writeText(code).then(() => toast("Cod AutoLISP copiat — lipește-l în linia de comandă AutoCAD pentru a selecta entitățile."));
  }));
  box.querySelectorAll("[data-handles]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(b.dataset.handles).then(() => toast("Handle-uri copiate."));
  }));
  const split = (v) => { const [id, ci, si] = v.split("|"); return [id, Number(ci), Number(si)]; };
  box.querySelectorAll("[data-rm-src]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    const [id, ci, si] = split(b.dataset.rmSrc);
    planComp(id, ci).sources.splice(si, 1);
    recompute();
  }));
  box.querySelectorAll("[data-tol]").forEach((inp) => {
    inp.addEventListener("click", (e) => e.stopPropagation());
    inp.addEventListener("change", () => {
      const [id, ci] = split(inp.dataset.tol);
      const v = parseFloat(inp.value);
      if (!Number.isNaN(v)) { planComp(id, ci).tolerance_m = v; recompute(); }
    });
  });
  box.querySelectorAll("[data-add-factor]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    const [id, ci] = split(b.dataset.addFactor);
    const name = prompt("Denumire factor (ex. grosime, înălțime cofraj):", "grosime");
    if (!name) return;
    const value = parseFloat((prompt("Valoare:", "0.10") || "").replace(",", "."));
    if (Number.isNaN(value)) return;
    const unit = prompt("Unitate: m (grosime/înălțime), m² (secțiune) sau - (multiplicator):", "m") || "m";
    const comp = planComp(id, ci);
    comp.factors = comp.factors || [];
    comp.factors.push({ name, value, unit: ["m", "m²", "-"].includes(unit) ? unit : "m", origin: "assumed", note: "adăugat manual" });
    const it = planItem(id);
    const dims = { area: 2, length: 1, perimeter: 1, count: 0, strip_area: 2, enclosed_area: 2, count_groups: 0 }[comp.measure] + comp.factors.reduce((a, f) => a + ({ m: 1, "m²": 2 }[f.unit] || 0), 0);
    it.unit = { 1: "m", 2: "m²", 3: "m³" }[dims] || it.unit;
    recompute();
  }));
  box.querySelectorAll("[data-rm-item]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!confirm("Ștergi acest element din listă?")) return;
    S.plan.items = S.plan.items.filter((x) => x.id !== b.dataset.rmItem);
    S.selected = null;
    recompute();
  }));
  box.querySelectorAll("[data-rename]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    const it = planItem(b.dataset.rename);
    const name = prompt("Denumire element:", it.label);
    if (name) { it.label = name; recompute(); }
  }));
  box.querySelectorAll(".factor input").forEach((inp) => {
    inp.addEventListener("click", (e) => e.stopPropagation());
    inp.addEventListener("change", () => {
      const v = parseFloat(inp.value);
      if (Number.isNaN(v)) return;
      const item = S.plan.items.find((x) => x.id === inp.dataset.item);
      const f = item.components[Number(inp.dataset.comp)].factors[Number(inp.dataset.factor)];
      f.value = v;
      if (!/modificat/.test(f.note || "")) f.note = (f.note ? f.note + " " : "") + "(modificat manual)";
      recompute();
    });
  });
}

export function selectItem(id, toggle) {
  S.selected = toggle && S.selected === id ? null : id;
  clearGroup("featureHl");
  renderResults();
  drawOverlays();
  const found = S.result && S.result.items.find((x) => x.id === id);
  if (S.selected && !found) S.selected = null;
  if (S.selected) {
    const it = found;
    const geo = { polygons: [], lines: [], points: [] };
    for (const c of it.components) { geo.polygons.push(...c.overlay.polygons); geo.lines.push(...c.overlay.lines); geo.points.push(...c.overlay.points); }
    if (geo.polygons.length || geo.lines.length || geo.points.length) zoomToGeom(geo, 1.15);
    const row = document.querySelector(`tr.item-row[data-id="${CSS.escape(id)}"]`);
    if (row && !toggle) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

async function exportXlsx() {
  const r = await fetch("/api/export/xlsx", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ result: S.result, project_name: S.project && S.project.name, project_id: S.pid }) });
  const blob = await r.blob();
  const base = ((S.project && S.project.name) || "planșă").replace(/\.(dwg|dxf)$/i, "").replace(/[^\w\-ăâîșțĂÂÎȘȚ ]+/g, "_").slice(0, 60);
  download(blob, `antemasuratoare - ${base}.xlsx`);
}
function copyTable() {
  const plain = (x, d = 2) => (x === null || x === undefined ? "" : Number(x).toFixed(d).replace(".", ","));
  const rows = [["Nr.", "Element", "Cantitate", "UM", "Status", "Formulă"]];
  S.result.items.forEach((it, i) => rows.push([i + 1, it.label, plain(it.value), it.unit || "", STATUS[it.status] || it.status, it.formula || ""]));
  const tsv = rows.map((r) => r.map((v) => String(v).replace(/[\t\n]/g, " ")).join("\t")).join("\n");
  navigator.clipboard.writeText(tsv).then(() => toast("Tabel copiat — lipiți-l în Excel."), () => toast("Copierea nu este permisă de browser."));
}

function exportJson() { download(new Blob([JSON.stringify(S.result, null, 1)], { type: "application/json" }), "rezultat.json"); }
function download(blob, name) {
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
