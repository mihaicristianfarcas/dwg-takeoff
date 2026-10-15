// Shared state, constants and small helpers (DOM, formatting, API calls).

export const S = {
  projects: [], pid: null, project: null,
  view: null, origin: [0, 0], size: [1, 1], twist: 0, rotate: true,
  vb: null, result: null, plan: null, query: "",
  selected: null, hidden: new Set(), job: null, activeLayer: null,
};
const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#be123c"];
export const STATUS = { measured: "Măsurat", assumption_based: "Cu ipoteze", not_in_drawing: "Lipsă în planșă" };
export const CONF = { high: "încredere mare", medium: "încredere medie", low: "încredere scăzută" };
export const MEASURE = { area: "arie", length: "lungime", perimeter: "perimetru", count: "număr", strip_area: "arie benzi", enclosed_area: "arie închisă de linii", count_groups: "număr grupuri" };
export const KIND = { hatch: "hașură", solid: "solid", closed: "contur închis", line: "linie", block: "bloc", text: "text", table_polygon: "contur din tabel" };
export const $ = (id) => document.getElementById(id);
export const NS = "http://www.w3.org/2000/svg";

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
export function num(x, d = 2) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return "—";
  const [i, f] = Math.abs(Number(x)).toFixed(d).split(".");
  const int = i.replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f");
  return (Number(x) < 0 ? "−" : "") + int + (f ? "," + f : "");
}
export function toast(msg, ms = 2600) {
  const t = $("toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
export async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) {
    o.method = o.method || "POST";
    o.headers = { "Content-Type": "application/json" };
    o.body = JSON.stringify(o.json);
    delete o.json;
  }
  const r = await fetch(path, o);
  if (r.status === 202) return { __pending: true, ...(await r.json()) };
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* ignore */ }
    const e = new Error(msg); e.status = r.status; throw e;
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r;
}
export function itemColor(i) { return PALETTE[i % PALETTE.length]; }
