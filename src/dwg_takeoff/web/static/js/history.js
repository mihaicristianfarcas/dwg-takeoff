// History of analyses of the drawing.

import { $, S, api, esc, toast } from "./core.js";
import { switchTab } from "./main.js";
import { EFFORT_RO, checkReuse, setResult } from "./ask.js";

export function fmtRun(run) { // 20261015-091530-123456 -> 15.10.2026 09:15
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(run || "");
  return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : run;
}

export async function loadRuns() {
  const box = $("history");
  if (!S.pid) return;
  let runs = [];
  try { runs = await api(`/api/projects/${S.pid}/runs`); } catch (_) { /* ignore */ }
  if (!runs.length) { box.innerHTML = `<p class="muted">Nicio analiză încă pentru această planșă.</p>`; return; }
  box.innerHTML = runs.map((r) => `<div class="history-item ${S.result && S.result.run === r.run ? "current" : ""}" data-run="${esc(r.run)}" tabindex="0" role="button">
      <div class="small muted">${esc(fmtRun(r.run))} · ${r.items} elemente${r.seconds ? ` · AI ${r.seconds} s` : ""}${r.backend ? ` · ${esc(r.backend)}${r.effort ? " " + esc(EFFORT_RO[r.effort] || r.effort) : ""}` : ""}${r.edited ? " · editat manual" : ""}
        <button class="btn-link danger hist-del" data-del="${esc(r.run)}" title="Șterge din istoric">șterge</button></div>
      <div>${esc(r.query)}</div></div>`).join("");
  box.querySelectorAll(".history-item").forEach((d) => {
    const open = async () => {
      const res = await api(`/api/projects/${S.pid}/runs/${d.dataset.run}`);
      setResult(res, true);
      if (res.query) $("query").value = res.query;
      switchTab("ask");
    };
    d.addEventListener("click", open);
    d.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
  box.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!confirm("Ștergi această analiză din istoric?")) return;
    try { await api(`/api/projects/${S.pid}/runs/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" }); S.runs = null; loadRuns(); checkReuse(); }
    catch (err) { toast("Eroare: " + err.message); }
  }));
}
