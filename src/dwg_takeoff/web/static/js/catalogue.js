// The element catalogue: every measurable group, with editable labels.

import { $, S, api, esc, num, toast } from "./core.js";
import { switchTab } from "./main.js";
import { L, clearGroup, el, linePath, polyPath } from "./viewer.js";
import { recompute } from "./ask.js";
import { selectItem } from "./results.js";
import { swatch } from "./explorer.js";

export const CAT_RO = {
  building: "Clădire / amprentă", wall: "Perete", door: "Ușă", window: "Fereastră", stair: "Scară", elevator: "Lift",
  room: "Încăpere", road: "Drum / carosabil", parking: "Parcare", paving: "Pavaj / alei", curb: "Bordură",
  concrete: "Beton (placă, fundație)", lawn: "Gazon", planting: "Plantații", tree: "Arbore", shrub: "Arbust / gard viu",
  fence: "Gard / împrejmuire", gravel: "Pietriș", wood: "Lemn / deck", stone: "Piatră", water: "Apă / bazin",
  play: "Joacă / sport", marking: "Marcaj rutier", furniture: "Mobilier urban / echipamente", vehicle: "Vehicul",
  drainage: "Canalizare / drenaj", utility: "Rețea utilități", boundary: "Limită proprietate",
  topography: "Topografie / cote", annotation: "Adnotare (nu se măsoară)",
};
const KIND_RO = { surface: "hașură", outline: "contur", linear: "linii", block: "bloc", nested_block: "bloc în bloc",
  table: "tabel trasare", part: "suprafață" };
const KIND_GROUP = { surface: "area", outline: "area", part: "area", table: "area", linear: "length", block: "count", nested_block: "count" };

export async function loadCatalogue() {
  const pid = S.pid, box = $("catalogue");
  if (!box) return;
  if (!S.catalogue || S.catalogue.pid !== pid) {
    try {
      const c = await api(`/api/projects/${pid}/catalogue`);
      if (S.pid !== pid) return;
      S.catalogue = { pid, ...c, open: new Set(), limit: 250 };
    } catch (err) { box.innerHTML = `<p class="small muted">Catalogul nu a putut fi încărcat: ${esc(err.message)}</p>`; return; }
  }
  renderCatalogue();
}

function entryQty(e) {
  if (e.measure === "count") return `${num(e.count ?? e.n, 0)}<span class="unit">buc</span>`;
  if (e.measure === "length") return `${num(e.length_dedup ?? e.length ?? 0)}<span class="unit">m</span>`;
  return e.area == null ? "—" : `${num(e.area)}<span class="unit">m²</span>`;
}

function entryInfo(e, c) {
  const bits = [KIND_RO[e.kind] || e.kind];
  if (e.layer) bits.push(esc(e.layer));
  if (e.in_block) bits.push(`în blocul ${esc(e.in_block)}`);
  if (e.block && e.kind !== "part") bits.push(`<span class="tag">${esc(e.block)}</span>`);
  if (e.pattern) bits.push(`<span class="tag">${esc(e.pattern)}</span>`);
  if (e.color && (e.kind !== "block" || e.split_color)) bits.push(`${swatch(e.color, (e.color_name || "") + " " + e.color)}${esc(e.color_name || "")}`);
  if (e.kind !== "part") bits.push(`×${c.site && e.n_site != null ? e.n_site : e.n}`);
  if (c.site && e.n_site != null && e.n_site < e.n) bits.push(e.n_site ? `<span class="tag">+${e.n - e.n_site} în afara zonei</span>` : `<span class="tag hidden">în afara zonei</span>`);
  if (!e.visible) bits.push(`<span class="tag hidden">ascuns</span>`);
  if (e.size_m) bits.push(`simbol ${num(e.size_m)} m`);
  if (e.width_m) bits.push(`lățime ${num(e.width_m)} m`);
  const ev = [];
  if (e.legend && e.legend.length) ev.push(`legendă: ${e.legend.map((x) => `„${esc(x)}”`).join(", ")}`);
  if (e.callouts && e.callouts.length) ev.push(`indicator: ${e.callouts.slice(0, 3).map((x) => `„${esc(x)}”`).join(", ")}`);
  if (e.kind !== "part" && e.texts && e.texts.length) ev.push(`texte: ${e.texts.slice(0, 3).map((x) => `„${esc(x)}”`).join(", ")}`);
  if (e.duplicates && e.duplicates.length) ev.push(`desenat și ca ${e.duplicates.filter((d) => d.id).map((d) => esc(d.id)).join(", ")}`);
  if (e.edges && e.edges.length) ev.push(`conturat de ${e.edges.filter((d) => d.id).map((d) => `${esc(d.id)}${d.legend && d.legend.length ? ` „${esc(d.legend[0])}”` : ""} (${Math.round(d.share * 100)}%)`).join(", ")}`);
  if (e.edge_of && e.edge_of.length) ev.push(`conturează ${e.edge_of.filter((d) => d.id).map((d) => esc(d.id)).join(", ")}`);
  if (e.descriptions && e.descriptions.length) ev.push(esc(e.descriptions[0]));
  if (e.used_in && e.used_in.length) {
    ev.push(`în analiză: ${e.used_in.slice(0, 2).map((x) => `„${esc(x)}”`).join(", ")}` + (e.label_source !== "user" && e.used_in.length === 1
      ? ` <button class="btn-link" data-adopt="${esc(e.key)}" title="Folosește denumirea elementului din analiză ca denumire a acestui element din catalog">folosește ca denumire</button>` : ""));
  }
  const kids = c.kids[e.key];
  if (kids) ev.push(`<button class="btn-link" data-open="${esc(e.key)}">${c.open.has(e.key) ? "▾" : "▸"} ${kids.length} suprafețe denumite</button>`);
  return bits.join(" · ") + (ev.length ? `<br>${ev.join(" · ")}` : "");
}

function renderCatalogue() {
  const c = S.catalogue, box = $("catalogue");
  if (!c || !box) return;
  c.kids = {};
  for (const e of c.entries) if (e.parent) (c.kids[e.parent] = c.kids[e.parent] || []).push(e);
  const f = c.filter || (c.filter = { q: "", kind: "", site: c.site, named: false });
  const q = f.q.toLowerCase();
  const match = (e) => (!f.kind || KIND_GROUP[e.kind] === f.kind)
    && (!f.site || !c.site || e.n_site == null || e.n_site > 0)
    && (!f.named || e.label || (e.category && e.category !== "annotation"))
    && (!q || [e.id, e.label, e.layer, e.block, e.in_block, e.pattern, CAT_RO[e.category], ...(e.legend || []), ...(e.callouts || []), ...(e.texts || [])]
      .some((x) => x && String(x).toLowerCase().includes(q)));
  const top = c.entries.filter((e) => !e.parent && (match(e) || (c.kids[e.key] || []).some(match)));
  const cats = `<option value="">—</option>` + c.categories.map((k) => `<option value="${esc(k.id)}">${esc(CAT_RO[k.id] || k.name)}</option>`).join("");
  const row = (e, part) => {
    const ph = e.category ? CAT_RO[e.category] || e.category : (e.layer || e.block || "fără nume");
    return `<tr class="cat-row clickable${part ? " part" : ""}" data-id="${esc(e.id)}" tabindex="0">
      <td class="cid">${esc(e.id)}</td>
      <td><input class="cat-label${e.label_source === "user" ? " user" : ""}" data-key="${esc(e.key)}" value="${esc(e.label || "")}" placeholder="${esc(ph)}" aria-label="Denumire ${esc(e.id)}"
          title="${e.label ? `Denumire din ${{ user: "corectura dvs.", legend: "legendă", callout: "indicator pe plan", text: "textul din interior" }[e.label_source] || e.label_source}` : "Adăugați o denumire"}">
        <div class="small muted cat-info">${entryInfo(e, c)}</div></td>
      <td><select class="cat-cat${e.category_source === "user" ? " user" : ""}" data-key="${esc(e.key)}" aria-label="Categorie ${esc(e.id)}" title="${e.category_source === "user" ? "categorie aleasă de dvs." : "categorie dedusă din denumiri"}">${cats.replace(`value="${esc(e.category || "")}"`, `value="${esc(e.category || "")}" selected`)}</select></td>
      <td class="num">${entryQty(e)}</td>
      <td class="nowrap"><button class="add" data-add-entry="${esc(e.id)}" title="Adaugă ca element în tabelul de cantități">+</button></td></tr>`;
  };
  let rows = "", n = 0;
  for (const e of top) {
    if (n >= c.limit) break;
    rows += row(e, false); n++;
    const kids = c.kids[e.key] || [];
    if (kids.length && (c.open.has(e.key) || (q && kids.some(match)))) for (const k of kids) if (!q || match(k)) rows += row(k, true);
  }
  box.innerHTML = `<div class="cat-filters">
      <input class="search" id="catSearch" placeholder="Caută id, denumire, strat, bloc, legendă, text…" aria-label="Caută în catalog" value="${esc(f.q)}">
      <select id="catKind" aria-label="Tip"><option value="">toate</option><option value="area">suprafețe</option><option value="length">linii</option><option value="count">blocuri</option></select>
      ${c.site ? `<label class="small"><input type="checkbox" id="catSite" ${f.site ? "checked" : ""}> doar în zona amenajată</label>` : ""}
      <label class="small"><input type="checkbox" id="catNamed" ${f.named ? "checked" : ""}> doar cele identificate</label>
    </div>
    <table class="ltable cat-table" id="catTable"><colgroup><col class="c-id"><col><col class="c-cat"><col class="c-q"><col class="c-add"></colgroup>
      <thead><tr><th>Id</th><th>Denumire</th><th>Categorie</th><th style="text-align:right">Cantitate</th><th><span class="sr-only">Adaugă</span></th></tr></thead>
      <tbody>${rows || `<tr><td colspan="5" class="muted small">Nimic nu corespunde filtrului.</td></tr>`}</tbody></table>
    ${top.length > c.limit ? `<button class="btn btn-sm" id="catMore">Arată toate (${top.length})</button>` : ""}`;
  $("catKind").value = f.kind;
  $("catSearch").addEventListener("input", (ev) => { f.q = ev.target.value; const pos = ev.target.selectionStart; renderCatalogue(); const i = $("catSearch"); i.focus(); i.setSelectionRange(pos, pos); });
  $("catKind").addEventListener("change", (ev) => { f.kind = ev.target.value; renderCatalogue(); });
  if ($("catSite")) $("catSite").addEventListener("change", (ev) => { f.site = ev.target.checked; renderCatalogue(); });
  $("catNamed").addEventListener("change", (ev) => { f.named = ev.target.checked; renderCatalogue(); });
  if ($("catMore")) $("catMore").addEventListener("click", () => { c.limit = 100000; renderCatalogue(); });
  box.querySelectorAll("[data-adopt]").forEach((b) => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const e = c.entries.find((x) => x.key === b.dataset.adopt);
    if (e && e.used_in.length) saveLabel(e.key, { label: e.used_in[0] });
  }));
  box.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const k = b.dataset.open; c.open.has(k) ? c.open.delete(k) : c.open.add(k); renderCatalogue();
  }));
  box.querySelectorAll("tr.cat-row").forEach((tr) => {
    const go = (ev) => { if (ev && ev.target.closest("input,select,button")) return; showEntry(tr.dataset.id, tr); };
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", (ev) => { if ((ev.key === "Enter" || ev.key === " ") && ev.target === tr) { ev.preventDefault(); go(); } });
  });
  box.querySelectorAll("input.cat-label").forEach((inp) => {
    inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") inp.blur(); });
    inp.addEventListener("change", () => saveLabel(inp.dataset.key, { label: inp.value }));
  });
  box.querySelectorAll("select.cat-cat").forEach((sel) => sel.addEventListener("change", () => saveLabel(sel.dataset.key, { category: sel.value })));
  box.querySelectorAll("button[data-add-entry]").forEach((b) => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    addEntryItem(c.entries.find((e) => e.id === b.dataset.addEntry));
  }));
}

async function saveLabel(key, change) {
  const c = S.catalogue, pid = S.pid;
  const e = c.entries.find((x) => x.key === key);
  const body = { key, label: e.label_source === "user" ? e.label : "", category: e.category_source === "user" ? e.category : null, ...change };
  try {
    const upd = await api(`/api/projects/${pid}/catalogue/label`, { method: "PUT", json: body });
    if (S.pid !== pid) return;
    Object.assign(e, upd);
    renderCatalogue();
    toast(`${e.id}: salvat — următoarea analiză AI folosește denumirea.`);
  } catch (err) { toast("Eroare la salvare: " + err.message, 5000); }
}

async function showEntry(id, tr) {
  clearGroup("layerHl");
  document.querySelectorAll("tr.active").forEach((x) => x.classList.remove("active"));
  const key = "entry:" + id;
  if (S.activeLayer === key) { S.activeLayer = null; return; }
  S.activeLayer = key;
  if (tr) tr.classList.add("active");
  try {
    const r = await api(`/api/projects/${S.pid}/entry/${encodeURIComponent(id)}`);
    if (S.activeLayer !== key) return;
    const g = $("layerHl"), geo = r.geometry;
    if (geo.polygons.length) el("path", { d: polyPath(geo.polygons), class: "hl-layer" }, g);
    if (geo.lines.length) el("path", { d: linePath(geo.lines), class: "hl-layer-line" }, g);
    for (const p of geo.points) { const [x, y] = L(p); el("circle", { cx: x, cy: y, r: 0.5, class: "hl-layer" }, g); }
    toast(`${id}: ${r.n} entități`);
  } catch (err) { toast("Eroare: " + err.message); }
}

function addEntryItem(e) {
  if (!e) return;
  const measure = { area: "area", length: "length", count: "count" }[e.measure] || "area";
  const what = [e.layer, e.in_block && `în ${e.in_block}`, e.block, e.pattern, e.color_name].filter(Boolean).join(" · ");
  const name = e.label || (e.category && e.category !== "annotation" ? `${CAT_RO[e.category]} (${what})` : what) || e.id;
  if (!S.plan) S.plan = { language: "ro", summary: "", items: [], general_notes: [], questions_for_user: [] };
  const id = "manual_" + Date.now().toString(36);
  const word = { area: "arie", length: "lungime", count: "număr" }[measure];
  const inSite = S.project.focus && e.n_site != null && e.n_site > 0;
  S.plan.items.push({
    id, label: `${name} – ${word}`, request_text: `adăugat din catalog (${e.id})`,
    unit: { area: "m²", length: "m", count: "buc" }[measure], status: "measured", confidence: "high",
    reasoning: `Element adăugat manual din catalog: ${e.id}${e.layer ? ` (stratul ${e.layer})` : ""}${inSite ? ", în zona amenajată" : ""}.`,
    components: [{ label: name, measure, entries: [e.id], subtract_entries: [], sources: [], subtract_sources: [],
      region: inSite ? "site" : null, tolerance_m: measure === "length" ? 0.3 : null, factors: [] }],
    assumptions: [], questions: [],
  });
  switchTab("ask");
  recompute().then((ok) => { if (ok) selectItem(id, false); });
}

export function tableHtml(rows) {
  return `<div class="table-scroll"><table>${rows.map((r) => `<tr>${r.map((v) => `<td>${esc(typeof v === "number" ? num(v, Number.isInteger(v) ? 0 : 2) : v)}</td>`).join("")}</tr>`).join("")}</table></div>`;
}

export async function showLayer(name, tr, pattern, color) {
  clearGroup("layerHl");
  document.querySelectorAll("tr.active").forEach((x) => x.classList.remove("active"));
  const key = [name, pattern || "", color || ""].join("|");
  if (S.activeLayer === key) { S.activeLayer = null; return; }
  S.activeLayer = key;
  if (tr) tr.classList.add("active");
  try {
    const q = new URLSearchParams({ name });
    if (pattern) q.set("pattern", pattern);
    if (color) q.set("color", color);
    const r = await api(`/api/projects/${S.pid}/layer?${q}`);
    if (S.activeLayer !== key) return;
    const g = $("layerHl");
    const geo = r.geometry;
    if (geo.polygons.length) el("path", { d: polyPath(geo.polygons), class: "hl-layer" }, g);
    if (geo.lines.length) el("path", { d: linePath(geo.lines), class: "hl-layer-line" }, g);
    for (const p of geo.points) { const [x, y] = L(p); el("circle", { cx: x, cy: y, r: 0.5, class: "hl-layer" }, g); }
    toast(`${name}${pattern ? " · " + pattern : ""}${color ? " · " + color : ""}: ${r.n} entități`);
  } catch (err) { toast("Eroare: " + err.message); }
}
