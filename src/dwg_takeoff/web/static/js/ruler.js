// The ruler: distances and areas measured on the plan, unit calibration.

import { $, S, num } from "./core.js";
import { setUnits } from "./units.js";
import { L, clearGroup, el, unitScale } from "./viewer.js";

S.ruler = false; S.rulerPts = []; S.rulerClosed = false;
export function setRuler(on) {
  S.ruler = on; S.rulerPts = []; S.rulerClosed = false;
  $("rulerBtn").classList.toggle("on", on);
  $("svg").classList.toggle("ruler", on);
  drawRuler();
}
// client point -> model coordinates (through the rotated content group)
function modelPoint(e) {
  const pt = $("svg").createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
  const l = pt.matrixTransform($("content").getScreenCTM().inverse());
  return [l.x + S.origin[0], -l.y + S.origin[1]];
}
export function rulerClick(e) {
  if (S.rulerClosed) { S.rulerPts = []; S.rulerClosed = false; }
  const p = modelPoint(e);
  const last = S.rulerPts[S.rulerPts.length - 1];
  if (last && Math.hypot(p[0] - last[0], p[1] - last[1]) < 1e-6) return;
  S.rulerPts.push(p);
  drawRuler();
}
// units from one known length: the last ruler segment is `segUnits` drawing units long
function calibrate(segUnits) {
  const ans = prompt(`Ultimul segment măsoară acum ${num(segUnits * unitScale())} m.\nCare este lungimea lui reală, în metri?`);
  const real = parseFloat((ans || "").replace(",", "."));
  if (!(real > 0) || !(segUnits > 0)) return;
  const scale = real / segUnits;
  // a standard unit within 1 % is used as such (mm, cm, m, ft, in), otherwise the exact scale
  const std = { 6: 1, 4: 0.001, 5: 0.01, 14: 0.1, 2: 0.3048, 1: 0.0254 };
  const code = Object.keys(std).find((c) => Math.abs(std[c] - scale) <= 0.01 * std[c]);
  setUnits(code ? Number(code) : null, code ? null : scale);
}
export function drawRuler() {
  clearGroup("rulerG");
  const box = $("rulerBox");
  const pts = S.rulerPts;
  if (!S.ruler) { box.hidden = true; return; }
  box.hidden = false;
  if (!pts.length) { box.innerHTML = "Riglă: click pe plan pentru a adăuga puncte · dublu-click închide poligonul · Esc șterge"; return; }
  const k = unitScale();
  const g = $("rulerG");
  const ring = S.rulerClosed ? [...pts, pts[0]] : pts;
  el("path", { d: "M" + ring.map((c) => L(c).map((v) => v.toFixed(3)).join(",")).join("L"), class: S.rulerClosed ? "ruler-line" : "ruler-line open" }, g);
  const r = Math.max(S.vb.w, S.vb.h) / 300;
  for (const c of pts) { const [x, y] = L(c); el("circle", { cx: x, cy: y, r, class: "ruler-pt" }, g); }
  let len = 0, seg = 0;
  for (let i = 1; i < ring.length; i++) { seg = Math.hypot(ring[i][0] - ring[i - 1][0], ring[i][1] - ring[i - 1][1]); len += seg; }
  let h = `Segment: <b>${num(seg * k)} m</b> · Total: <b>${num(len * k)} m</b>`;
  if (S.rulerClosed) {
    let a = 0;
    for (let i = 0; i < pts.length; i++) { const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length]; a += x1 * y2 - x2 * y1; }
    h += ` · Arie: <b>${num(Math.abs(a) / 2 * k * k)} m²</b>`;
  }
  box.innerHTML = h + ` <span class="muted">(${pts.length} puncte)</span>` +
    (!S.rulerClosed && pts.length >= 2 ? ` <button class="btn-link" id="calibrateBtn" title="Dacă știți lungimea reală a ultimului segment (o cotă, o latură cunoscută), unitățile desenului se calibrează după ea">Calibrează unitățile…</button>` : "");
  if ($("calibrateBtn")) $("calibrateBtn").addEventListener("click", () => calibrate(seg));
}
