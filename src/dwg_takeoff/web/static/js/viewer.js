// The plan viewer: pan / zoom / rotation, background image and tiles, overlays.

import { $, NS, S, api, esc, itemColor, num, toast } from "./core.js";
import { drawRuler, rulerClick } from "./ruler.js";
import { selectItem } from "./results.js";

export function viewerMsg(msg) { const m = $("viewerMsg"); m.innerHTML = msg; m.hidden = !msg; }
export function clearGroup(id) { const g = $(id); while (g.firstChild) g.removeChild(g.firstChild); }

// zoom the view by factor k around the client point (cx, cy)
function zoomAt(cx, cy, k) {
  if (!S.vb) return;
  const p = svgPoint({ clientX: cx, clientY: cy });
  S.vb = { x: p.x - (p.x - S.vb.x) * k, y: p.y - (p.y - S.vb.y) * k, w: S.vb.w * k, h: S.vb.h * k };
  setViewBox();
}

export function setupViewer() {
  const svg = $("svg");
  // pointer events: mouse, pen and touch alike; two fingers pan + pinch-zoom
  const pts = new Map();
  let drag = null;
  svg.addEventListener("wheel", (e) => {
    if (!S.vb) return;
    e.preventDefault();
    // Firefox reports mouse wheels in lines (deltaMode 1), some devices in pages (2)
    let dy = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? svg.clientHeight : 1);
    if (e.ctrlKey) dy *= 4; // trackpad pinch (Chrome, Firefox, Edge) arrives as ctrl+wheel with small deltas
    zoomAt(e.clientX, e.clientY, Math.exp(Math.max(-300, Math.min(300, dy)) * 0.0015));
  }, { passive: false });
  // Safari: trackpad pinch arrives as gesture events (and would otherwise zoom the whole page)
  let gscale = 1;
  svg.addEventListener("gesturestart", (e) => { e.preventDefault(); gscale = 1; });
  svg.addEventListener("gesturechange", (e) => { e.preventDefault(); zoomAt(e.clientX, e.clientY, gscale / e.scale); gscale = e.scale; });
  svg.addEventListener("gestureend", (e) => e.preventDefault());

  const startDrag = () => {
    const c = centroid();
    drag = { x: c.x, y: c.y, vb: { ...S.vb }, moved: drag ? drag.moved : false, dist: spread() };
  };
  const centroid = () => { let x = 0, y = 0; for (const p of pts.values()) { x += p.x; y += p.y; } return { x: x / pts.size, y: y / pts.size }; };
  const spread = () => { if (pts.size < 2) return 0; const [a, b] = [...pts.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
  svg.addEventListener("pointerdown", (e) => {
    if (!S.vb || (e.pointerType === "mouse" && e.button !== 0)) return;
    svg.setPointerCapture(e.pointerId);
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    startDrag();
    svg.classList.add("panning");
  });
  svg.addEventListener("pointermove", (e) => {
    if (S.vb) showCursor(e);
    if (!pts.has(e.pointerId) || !drag) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const c = centroid();
    if (Math.abs(c.x - drag.x) + Math.abs(c.y - drag.y) > 3) drag.moved = true;
    const r = svg.getBoundingClientRect();
    let vb = { ...drag.vb };
    if (pts.size >= 2 && drag.dist > 0) { // pinch: scale the starting view around the gesture centre
      const k = drag.dist / Math.max(spread(), 1);
      const s0 = Math.max(vb.w / r.width, vb.h / r.height);
      const ax = vb.x + (drag.x - r.left) * s0, ay = vb.y + (drag.y - r.top) * s0;
      vb = { x: ax - (ax - vb.x) * k, y: ay - (ay - vb.y) * k, w: vb.w * k, h: vb.h * k };
      drag.moved = true;
    }
    const s = Math.max(vb.w / r.width, vb.h / r.height);
    S.vb = { ...vb, x: vb.x - (c.x - drag.x) * s, y: vb.y - (c.y - drag.y) * s };
    setViewBox();
  });
  const end = (e) => {
    if (!pts.has(e.pointerId)) return;
    const wasTap = drag && !drag.moved && pts.size === 1 && e.type === "pointerup";
    pts.delete(e.pointerId);
    if (wasTap && S.ruler) rulerClick(e);
    if (pts.size) startDrag(); else { drag = null; svg.classList.remove("panning"); }
  };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);
  svg.addEventListener("dblclick", (e) => { if (S.ruler && S.rulerPts.length >= 3) { S.rulerClosed = true; drawRuler(); } e.preventDefault(); });
  new ResizeObserver(() => { if (S.vb) { setViewBox(); drawScaleBar(); } }).observe($("viewer"));
  // keyboard: + / - zoom, arrows pan, 0 fits (when the plan has focus)
  $("viewer").addEventListener("keydown", (e) => {
    if (!S.vb) return;
    const r = svg.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const step = 0.15 * Math.max(S.vb.w, S.vb.h);
    const act = { "+": () => zoomAt(cx, cy, 0.8), "=": () => zoomAt(cx, cy, 0.8), "-": () => zoomAt(cx, cy, 1.25), "0": () => fit(),
      ArrowLeft: () => { S.vb.x -= step; setViewBox(); }, ArrowRight: () => { S.vb.x += step; setViewBox(); },
      ArrowUp: () => { S.vb.y -= step; setViewBox(); }, ArrowDown: () => { S.vb.y += step; setViewBox(); } }[e.key];
    if (act) { e.preventDefault(); act(); }
  });
}

function svgPoint(e) {
  const svg = $("svg");
  const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}

function showCursor(e) {
  const g = $("content");
  const ctm = g.getScreenCTM();
  if (!ctm) return;
  const pt = $("svg").createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
  const l = pt.matrixTransform(ctm.inverse());
  const x = l.x + S.origin[0], y = -l.y + S.origin[1];
  $("cursorPos").textContent = `X ${x.toFixed(2)}  Y ${y.toFixed(2)}`;
}

function setViewBox() {
  const v = S.vb;
  $("svg").setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
  drawScaleBar();
  clearTimeout(S.tilesT);
  S.tilesT = setTimeout(updateTiles, 250);
}

// deep zoom: sharper tiles of the visible area once the background image is magnified
const TILE_PX = 1024, TILE_MAX_LEVEL = 5;
function updateTiles() {
  const g = $("tiles");
  if (!S.vb || !S.project || !S.viewReady) { clearGroup("tiles"); return; }
  const [W, H] = S.size;
  const a = (-rotationDeg() * Math.PI) / 180, cx = W / 2, cy = -H / 2;
  const pts = [[S.vb.x, S.vb.y], [S.vb.x + S.vb.w, S.vb.y], [S.vb.x, S.vb.y + S.vb.h], [S.vb.x + S.vb.w, S.vb.y + S.vb.h]]
    .map(([x, y]) => { const dx = x - cx, dy = y - cy; return [cx + dx * Math.cos(a) - dy * Math.sin(a), cy + dx * Math.sin(a) + dy * Math.cos(a)]; });
  const lx0 = Math.min(...pts.map((p) => p[0])), lx1 = Math.max(...pts.map((p) => p[0]));
  const ly0 = Math.min(...pts.map((p) => p[1])), ly1 = Math.max(...pts.map((p) => p[1]));
  const screenPx = $("svg").getBoundingClientRect().width * (window.devicePixelRatio || 1);
  const need = (screenPx * W) / (TILE_PX * Math.max(lx1 - lx0, 1e-9)); // tiles across the window for 1:1 pixels
  const base = (S.view && S.view.px ? S.view.px[0] : 5000) / TILE_PX;
  const z = Math.min(TILE_MAX_LEVEL, Math.ceil(Math.log2(Math.max(need, 1))));
  if (need <= base * 1.05 || z < 1) { clearGroup("tiles"); return; }
  const n = 2 ** z, tw = W / n, th = H / n;
  const i0 = Math.max(0, Math.floor(lx0 / tw)), i1 = Math.min(n - 1, Math.floor(lx1 / tw));
  const j0 = Math.max(0, Math.floor(-ly1 / th)), j1 = Math.min(n - 1, Math.floor(-ly0 / th));
  if ((i1 - i0 + 1) * (j1 - j0 + 1) > 16) { clearGroup("tiles"); return; }
  const want = new Set();
  for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) want.add(`${z}/${i}/${j}`);
  [...g.children].forEach((im) => { if (!want.has(im.dataset.key)) im.remove(); });
  const have = new Set([...g.children].map((im) => im.dataset.key));
  for (const key of want) {
    if (have.has(key)) continue;
    const [, i, j] = key.split("/").map(Number);
    const im = el("image", { x: i * tw, y: -(j + 1) * th, width: tw, height: th, preserveAspectRatio: "none" }, g);
    im.dataset.key = key;
    const done = () => { im.dataset.loaded = "1"; tileState(); };
    im.addEventListener("load", done);
    im.addEventListener("error", () => { im.remove(); tileState(); });
    im.setAttribute("href", `/api/projects/${S.pid}/tile/${key}.png?v=${S.view.v || ""}`);
  }
  tileState();
}
function tileState() {
  const pending = [...$("tiles").children].filter((im) => !im.dataset.loaded).length;
  $("tileState").textContent = pending ? `se randează detaliile (${pending})…` : "";
}

export function unitScale() { return (S.project && S.project.unit_scale) || 1; }

// scale bar (a round length that fits ~120 px) and a north arrow following the view rotation
function drawScaleBar() {
  const box = $("scaleBar");
  if (!S.vb || !S.project) { box.hidden = true; return; }
  const r = $("svg").getBoundingClientRect();
  if (!r.width) return;
  const mPerPx = Math.max(S.vb.w / r.width, S.vb.h / r.height) * unitScale();
  const target = 120 * mPerPx;
  const p10 = Math.pow(10, Math.floor(Math.log10(target)));
  const len = [5, 2, 1].map((k) => k * p10).find((v) => v <= target) || p10;
  const label = len >= 1000 ? `${num(len / 1000, len % 1000 ? 1 : 0)} km` : len >= 1 ? `${num(len, 0)} m` : `${num(len * 100, 0)} cm`;
  box.hidden = false;
  $("scaleBarLine").style.width = `${(len / mPerPx).toFixed(1)}px`;
  $("scaleBarLabel").textContent = label;
  $("northArrow").style.transform = `rotate(${rotationDeg()}deg)`;
}

// model -> local svg coordinates (origin shifted, y flipped)
export function L(c) { return [c[0] - S.origin[0], -(c[1] - S.origin[1])]; }

function rotationDeg() { return S.rotate ? -S.twist : 0; }
export function applyRotation() {
  const [w, h] = S.size;
  $("content").setAttribute("transform", `rotate(${rotationDeg()} ${w / 2} ${-h / 2})`);
  $("rotateBtn").textContent = S.rotate ? "Orientare planșă" : "Nord în sus";
  $("rotateBtn").hidden = !S.twist;
  drawScaleBar();
}

function rotPt(x, y) {
  const a = (rotationDeg() * Math.PI) / 180, [w, h] = S.size;
  const cx = w / 2, cy = -h / 2;
  const dx = x - cx, dy = y - cy;
  return [cx + dx * Math.cos(a) - dy * Math.sin(a), cy + dx * Math.sin(a) + dy * Math.cos(a)];
}

export function fit(bboxLocal) {
  let [x0, y0, x1, y1] = bboxLocal || (S.project && S.project.focus ? polysBBox(S.project.focus.polygon.map((p) => p.map((r) => r.map(L)))) : [0, -S.size[1], S.size[0], 0]);
  const pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([x, y]) => rotPt(x, y));
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  let bx0 = Math.min(...xs), bx1 = Math.max(...xs), by0 = Math.min(...ys), by1 = Math.max(...ys);
  const r = $("viewer").getBoundingClientRect();
  const pad = 0.06 * Math.max(bx1 - bx0, by1 - by0) + 0.5;
  bx0 -= pad; bx1 += pad; by0 -= pad; by1 += pad;
  let w = bx1 - bx0, h = by1 - by0;
  const aspect = r.width / Math.max(r.height, 1);
  if (w / h < aspect) { const nw = h * aspect; bx0 -= (nw - w) / 2; w = nw; } else { const nh = w / aspect; by0 -= (nh - h) / 2; h = nh; }
  S.vb = { x: bx0, y: by0, w, h };
  setViewBox();
}

function polysBBox(polys) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const poly of polys) for (const ring of poly) for (const [x, y] of ring) {
    if (x < x0) x0 = x; if (y < y0) y0 = y; if (x > x1) x1 = x; if (y > y1) y1 = y;
  }
  return [x0, y0, x1, y1];
}
function geomBBoxLocal(g) {
  const polys = [...(g.polygons || []).map((p) => p.map((r) => r.map(L))), ...(g.lines || []).map((l) => [l.map(L)]), ...(g.points || []).map((p) => [[L(p)]])];
  return polys.length ? polysBBox(polys) : null;
}

export async function loadView() {
  const p = S.project;
  let v;
  try { v = await api(`/api/projects/${S.pid}/view`); } catch (err) { viewerMsg("Eroare la randare: " + err.message); return; }
  const b = v.bounds;
  S.origin = [b[0], b[1]];
  S.size = [b[2] - b[0], b[3] - b[1]];
  S.twist = p.focus ? p.focus.twist_deg : 0;
  applyRotation();
  if (p.focus) $("siteOutline").setAttribute("d", polyPath(p.focus.polygon));
  if (v.__pending) {
    viewerMsg("Se randează planul de fundal (doar prima dată, ~1 minut)…");
    if (!S.vb) fit();
    drawOverlays();
    setTimeout(() => S.project === p && loadView(), 4000);
    return;
  }
  const img = $("bgImage");
  img.setAttribute("x", 0); img.setAttribute("y", -S.size[1]);
  img.setAttribute("width", S.size[0]); img.setAttribute("height", S.size[1]);
  img.setAttribute("href", v.image);
  S.view = { px: v.px, v: (v.image.split("v=")[1] || "") };
  S.viewReady = true;
  clearGroup("tiles");
  viewerMsg("");
  if (!S.vb) fit();
  drawOverlays();
}

function ringPath(ring) {
  return "M" + ring.map((c) => { const [x, y] = L(c); return `${x.toFixed(3)},${y.toFixed(3)}`; }).join("L") + "Z";
}
export function polyPath(polys) { return polys.map((poly) => poly.map(ringPath).join("")).join(""); }
export function linePath(lines) {
  return lines.map((ln) => "M" + ln.map((c) => { const [x, y] = L(c); return `${x.toFixed(3)},${y.toFixed(3)}`; }).join("L")).join("");
}
export function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

function drawGeom(parent, g, color, cls = {}) {
  if (g.polygons && g.polygons.length) el("path", { d: polyPath(g.polygons), class: cls.poly || "ov-poly", fill: color, "fill-opacity": cls.fillOpacity ?? 0.38, stroke: color }, parent);
  if (g.lines && g.lines.length) el("path", { d: linePath(g.lines), class: cls.line || "ov-line", stroke: color }, parent);
  if (g.removed && g.removed.length) el("path", { d: linePath(g.removed), class: "ov-removed" }, parent);
  for (const p of g.points || []) { const [x, y] = L(p); el("circle", { cx: x, cy: y, r: 0.45, class: "ov-point", fill: color }, parent); }
}

export function drawOverlays() {
  clearGroup("overlays");
  const legend = $("mapLegend");
  if (!S.result) { legend.hidden = true; return; }
  const g = $("overlays");
  const items = S.result.items;
  const order = items.map((it, i) => i).sort((a, b) => (items[a].id === S.selected) - (items[b].id === S.selected));
  for (const i of order) {
    const it = items[i];
    if (S.hidden.has(it.id) && S.selected !== it.id) continue;
    if (S.selected && S.selected !== it.id) continue;
    const grp = el("g", { "data-item": it.id }, g);
    for (const c of it.components) {
      drawGeom(grp, c.overlay, itemColor(i), { fillOpacity: S.selected === it.id ? 0.5 : 0.38 });
    }
    grp.addEventListener("click", (e) => { if (S.ruler) return; e.stopPropagation(); selectItem(it.id, false); });
  }
  legend.hidden = false;
  if (S.legendOpen === undefined) S.legendOpen = $("viewer").clientWidth >= 560;
  legend.classList.toggle("collapsed", !S.legendOpen);
  legend.innerHTML = `<button class="legend-toggle" id="legendToggle" aria-expanded="${S.legendOpen}">${S.legendOpen ? "▾" : "▸"} Elemente pe plan (${items.length})</button><div class="legend-body">` + items.map((it, i) => {
    const has = it.components.some((c) => c.overlay.polygons.length || c.overlay.lines.length || c.overlay.points.length);
    return `<label title="${has ? "" : "fără geometrie pe plan"}"><input type="checkbox" data-id="${esc(it.id)}" ${S.hidden.has(it.id) ? "" : "checked"} ${has ? "" : "disabled"}>
      <span class="swatch" style="background:${itemColor(i)};${has ? "" : "opacity:.35"}"></span>${esc(it.label)}</label>`;
  }).join("") + `<div class="small muted" style="margin-top:4px">linie punctată gri = dubluri eliminate</div></div>`;
  $("legendToggle").addEventListener("click", () => { S.legendOpen = !S.legendOpen; drawOverlays(); });
  legend.querySelectorAll("input").forEach((cb) => cb.addEventListener("change", () => {
    if (cb.checked) S.hidden.delete(cb.dataset.id); else S.hidden.add(cb.dataset.id);
    drawOverlays();
  }));
}

export function zoomToGeom(g, factor = 2.5) {
  const bb = geomBBoxLocal(g);
  if (!bb) return;
  const cx = (bb[0] + bb[2]) / 2, cy = (bb[1] + bb[3]) / 2;
  const half = Math.max(bb[2] - bb[0], bb[3] - bb[1], 6) * factor / 2;
  fit([cx - half, cy - half, cx + half, cy + half]);
}

export async function highlightFeature(fid) {
  clearGroup("featureHl");
  if (fid === null || fid === undefined) return;
  try {
    const f = await api(`/api/projects/${S.pid}/features/${fid}`);
    const g = $("featureHl");
    const geo = f.geometry;
    if (geo.polygons.length) el("path", { d: polyPath(geo.polygons), class: "hl-feature" }, g);
    if (geo.lines.length) el("path", { d: linePath(geo.lines), class: "hl-feature-line" }, g);
    for (const p of geo.points) { const [x, y] = L(p); el("circle", { cx: x, cy: y, r: 0.8, class: "hl-feature" }, g); }
    zoomToGeom(geo);
    toast(`${f.handle} · ${f.layer} · ${f.kind}${f.area ? " · " + num(f.area) + " m²" : ""}${!f.area && f.length ? " · " + num(f.length) + " m" : ""}`);
  } catch (err) { toast("Eroare: " + err.message); }
}
