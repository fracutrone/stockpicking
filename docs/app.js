"use strict";

const AREAS = [
  ["nucleo", "Nucleo", "var(--a1)"], ["valutazione", "Valutazione", "var(--a2)"], ["moat", "Moat", "var(--a3)"],
  ["macro", "Macro/TAM", "var(--a4)"], ["protezione", "Protezione", "var(--a5)"], ["tecnica", "Tecnica", "var(--a6)"],
];
const TRACKS = { usuale: "Settore usuale", banca: "Banca", assicurazione: "Assicurazione", reit: "REIT", escluso_biotech: "Biotech (fuori modello)", escluso_nosettore: "Senza settore (fuori modello)" };

// etichetta, formato
const L = {
  revenue_cagr: ["CAGR ricavi", "pct"], ebitda_cagr: ["CAGR EBITDA", "pct"], net_income_cagr: ["CAGR utile netto", "pct"],
  fcf_margin: ["Margine FCF (3 anni)", "pct"], fcf_positive_share: ["Anni con FCF positivo", "share"],
  net_margin: ["Margine netto", "pct"], debt_to_equity: ["Debt/Equity", "x2"], net_debt_to_ebitda: ["PFN/EBITDA", "x"],
  interest_coverage: ["Copertura interessi", "x"], ev_ebitda: ["EV/EBITDA", "x"], pe: ["P/E", "x"], p_fcf: ["P/FCF", "x"],
  pb: ["P/B", "x2"], ev_ebitda_vs_own_history: ["EV/EBITDA vs media storica", "ratio"],
  roic_avg: ["ROIC medio", "pct"], roic_above_peer_share: ["Anni con ROIC sopra mediana", "share"],
  roic_stability: ["Variabilità ROIC (CV)", "cv"], gross_margin_avg: ["Margine lordo medio", "pct"],
  gross_margin_stability: ["Volatilità margine lordo", "negpp"],
  peer_revenue_cagr: ["CAGR ricavi del settore", "pct"], peer_growth_consistency: ["Anni di crescita del settore", "share"],
  share_gain: ["Crescita vs settore", "pp"], beneish_m: ["Beneish M-Score", "n2"], altman_z: ["Altman Z-Score", "n2"],
  ncav_to_mcap: ["NCAV / capitalizzazione", "pct"], rsi14: ["RSI 14 giorni", "n1"], dist_sma200: ["Distanza da SMA200", "pct"],
  short_pct_float: ["Short interest / flottante", "pct"], roe_avg: ["ROE medio", "pct"], cost_income: ["Cost/Income", "pct"],
  nii_cagr: ["CAGR margine d'interesse", "pct"], equity_to_assets: ["Patrimonio / attivo", "pct"],
  ptbv_gap: ["P/TBV vs teorico", "ratio"], roe_above_peer_share: ["Anni con ROE sopra mediana", "share"],
  roe_stability: ["Variabilità ROE (CV)", "cv"], cost_income_stability: ["Volatilità cost/income", "negpp"],
  profit_positive_share: ["Anni in utile", "share"], ffo_cagr: ["CAGR FFO", "pct"], ffo_margin: ["Margine FFO", "pct"],
  p_ffo: ["P/FFO", "x"], ebitda_margin_avg: ["Margine EBITDA medio", "pct"],
  ebitda_margin_stability: ["Volatilità margine EBITDA", "negpp"], debt_to_assets: ["Debito / attivo", "pct"],
};

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ok = (v) => v !== null && v !== undefined && !Number.isNaN(v);

function fmt(v, f) {
  if (!ok(v)) return "n.d.";
  switch (f) {
    case "pct": return (v * 100).toFixed(1) + "%";
    case "share": return (v * 100).toFixed(0) + "%";
    case "x": return v.toFixed(1) + "x";
    case "x2": return v.toFixed(2) + "x";
    case "ratio": return v.toFixed(2) + "x";
    case "cv": return (-v).toFixed(2);
    case "negpp": return (-v * 100).toFixed(1) + " pp";
    case "pp": return (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + " pp";
    case "n1": return v.toFixed(1);
    case "n2": return v.toFixed(2);
    default: return String(v);
  }
}
function money(v, ccy = "") {
  if (!ok(v)) return "n.d.";
  const a = Math.abs(v);
  const s = a >= 1e12 ? (v / 1e12).toFixed(2) + " T" : a >= 1e9 ? (v / 1e9).toFixed(1) + " Mld" : a >= 1e6 ? (v / 1e6).toFixed(0) + " M" : v.toFixed(0);
  return s + (ccy ? " " + ccy : "");
}
// confronto con la mediana: buono / in linea / peggiore
function verdict(v, med, dir) {
  if (!ok(v) || !ok(med)) return "mid";
  const rel = med !== 0 ? (v - med) / Math.abs(med) : v - med;
  if (Math.abs(rel) < 0.05) return "mid";
  const better = dir === "low" ? v < med : v > med;
  return better ? "good" : "bad";
}

const state = { rows: [], meta: null, sort: { k: "rank", asc: true }, status: "classificato" };

async function init() {
  const res = await fetch("data/ranking.json", { cache: "no-store" });
  const data = await res.json();
  state.rows = data.rows;
  state.meta = data.meta;
  const d = new Date(state.meta.generated_at);
  $("#meta").textContent = `Aggiornato ${d.toLocaleString("it-IT", { dateStyle: "medium", timeStyle: "short" })} · ${state.meta.universe} titoli analizzati`;
  const c = state.meta.counts;
  $("#counts").innerHTML = [["Classificati", c["classificato"]], ["Esclusi (red flag)", c["escluso"]],
    ["Storico insufficiente", c["storico insufficiente"]], ["Fuori modello", c["fuori modello"]]]
    .filter((x) => x[1]).map((x) => `<span class="chip">${x[0]} <b>${x[1]}</b></span>`).join("");
  const sectors = [...new Set(state.rows.map((r) => r.sector))].sort();
  $("#sector").innerHTML += sectors.map((s) => `<option>${esc(s)}</option>`).join("");

  ["#q", "#region", "#sector", "#track"].forEach((s) => $(s).addEventListener("input", render));
  $("#status").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.status = b.dataset.v;
    [...$("#status").children].forEach((x) => x.classList.toggle("on", x === b));
    state.sort = state.status === "classificato" ? { k: "rank", asc: true } : { k: "score", asc: false };
    render();
  });
  document.querySelectorAll("th[data-k]").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k;
    state.sort = state.sort.k === k ? { k, asc: !state.sort.asc } : { k, asc: k === "rank" || k === "t" };
    render();
  }));
  $("#rows").addEventListener("click", (e) => { const tr = e.target.closest("tr"); if (tr) open(tr.dataset.t); });
  $("#scrim").addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  window.addEventListener("hashchange", fromHash);
  render();
  fromHash();
  loadTrack();
  loadPortfolio();
}

async function loadPortfolio() {
  try {
    const p = await (await fetch("data/portfolio.json", { cache: "no-store" })).json();
    const exCell = (e) => !e || !e.length ? `<span class="good-t">–</span>` : `<span class="${e.some((x) => x.startsWith("Esci")) ? "bad" : "mid"}-t">${e.map(esc).join("<br>")}</span>`;
    const head = `<tr><th>Titolo</th><th>Gruppo</th><th>#</th><th>Score</th><th>Peso</th><th>Settore</th><th>Paese</th><th>Segnali</th></tr>`;
    const row = (r) => `<tr class="clk" data-t="${esc(r.t)}"><td><b>${esc(r.t)}</b> <span class="note">${esc(r.n)}</span></td><td>${esc(r.bucket || "")}</td><td>${r.rank ?? "–"}</td><td>${ok(r.score) ? r.score.toFixed(1) : "–"}</td><td>${ok(r.weight) ? (r.weight * 100).toFixed(1) + "%" : ""}</td><td>${esc(r.sector || "")}</td><td>${esc(r.country || "")}</td><td>${exCell(r.exit)}</td></tr>`;
    let html = "";
    if (p.mine && p.mine.length) html += `<h4>I miei titoli</h4><table class="hist">${head}${p.mine.map(row).join("")}</table>`;
    if (p.model && p.model.length) html += `<h4>Portafoglio modello</h4><table class="hist">${head}${p.model.map(row).join("")}</table>
      <p class="note">Selezione automatica dalla classifica: Conviction ${p.rules.buckets.conviction.weight * 100}% · Protective ${p.rules.buckets.protective.weight * 100}% · Cyclical ${p.rules.buckets.cyclical.weight * 100}%, massimo ${p.rules.max_per_sector} titoli per settore e ${p.rules.max_country_share * 100}% per paese, esclusi i possibili value trap. Non è una raccomandazione d'acquisto.</p>`;
    if (!html) return;
    $("#pf-body").innerHTML = html;
    $("#pf-sum").textContent = ` · ${p.model.length} titoli${p.mine && p.mine.length ? ` · ${p.mine.length} monitorati` : ""}`;
    $("#pf-body").addEventListener("click", (e) => { const tr = e.target.closest("tr.clk"); if (tr) open(tr.dataset.t); });
    $("#portfolio").hidden = false;
  } catch (e) { /* nessun portafoglio */ }
}

async function loadTrack() {
  try {
    const t = await (await fetch("data/track.json", { cache: "no-store" })).json();
    if (!t.rows || !t.rows.length) return;
    const pc = (v) => ok(v) ? `<span class="${v >= 0 ? "good" : "bad"}-t">${(v >= 0 ? "+" : "") + (v * 100).toFixed(1)}%</span>` : "–";
    $("#track-tbl").innerHTML = `<tr><th>Classifica del</th><th>Giorni</th><th>Top ${t.top_n}</th><th>Portafoglio modello</th><th>Universo</th><th>MSCI World</th><th>Top vs universo</th><th>Top vs MSCI</th></tr>` +
      t.rows.slice().reverse().map((r) => `<tr title="${esc(r.top30_tickers)}"><td>${esc(r.start)}</td><td>${r.days}</td><td>${pc(r.top30)}</td><td>${pc(r.portafoglio_modello)}</td><td>${pc(r.universo)}</td><td>${pc(r.msci_world)}</td><td>${pc(r.extra_vs_universo)}</td><td>${pc(r.extra_vs_msci)}</td></tr>`).join("");
    const first = t.rows[0];
    $("#track-sum").textContent = ` · ${t.rows.length} fotografie mensili dal ${first.start}`;
    $("#history").hidden = false;
  } catch (e) { /* nessuno storico ancora */ }
}

function sortVal(r, k) {
  if (k === "k1" || k === "k2") return r[k].v;
  if (k === "flags") return r.flags.length;
  return r[k];
}

function render() {
  const q = $("#q").value.trim().toLowerCase();
  const reg = $("#region").value, sec = $("#sector").value, tr = $("#track").value;
  let rows = state.rows.filter((r) => {
    if (state.status === "altro" ? ["classificato", "escluso"].includes(r.status) : r.status !== state.status) return false;
    if (reg && r.region !== reg) return false;
    if (sec && r.sector !== sec) return false;
    if (tr && r.track !== tr) return false;
    if (q && !(r.t.toLowerCase().includes(q) || (r.n || "").toLowerCase().includes(q))) return false;
    return true;
  });
  const { k, asc } = state.sort;
  rows.sort((a, b) => {
    const x = sortVal(a, k), y = sortVal(b, k);
    if (!ok(x) && !ok(y)) return 0; if (!ok(x)) return 1; if (!ok(y)) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
  });
  document.querySelectorAll("th[data-k]").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.k === k); th.classList.toggle("asc", th.dataset.k === k && asc);
  });
  $("#empty").hidden = rows.length > 0;
  $("#rows").innerHTML = rows.slice(0, 1500).map(rowHtml).join("");
}

function cmpCell(o, dir) {
  if (!ok(o.v)) return `<span class="mid-t">n.d.</span>`;
  const f = o.label.startsWith("ROIC") || o.label.startsWith("ROE") || o.label.startsWith("Margine") ? "pct" : "x";
  const vd = verdict(o.v, o.med, dir);
  return `<span class="cmp"><span class="v ${vd}-t">${fmt(o.v, f)}</span> <span class="m">vs ${fmt(o.med, f)}</span></span>`;
}

function badges(r) {
  const b = [];
  if (r.pf) b.push(`<span class="badge pf" title="Nel portafoglio modello (${(r.pf * 100).toFixed(1)}%)">PF</span>`);
  if (r.bucket) b.push(`<span class="badge bk">${esc(r.bucket)}</span>`);
  if (r.vt) b.push(`<span class="badge vt" title="Possibile value trap">value trap?</span>`);
  if (r.dq === "verificato") b.push(`<span class="badge ok" title="Bilancio confrontato con la fonte ufficiale">✓ dati</span>`);
  return b.join(" ");
}

function rowHtml(r) {
  const bar = AREAS.map(([k, , c]) => `<span style="width:${((r.areas[k] || 0) / 100) * 100}%;background:${c}" title="${k} ${fmt(r.areas[k], "n1")}"></span>`).join("");
  const flag = r.status === "classificato" ? `<span class="pill good">Sano</span>`
    : r.status === "escluso" ? `<span class="pill bad" title="${esc(r.flags.join(" · "))}">${r.flags.length} red flag</span>`
    : `<span class="pill mid" title="${esc(r.flags.join(" · "))}">${esc(r.status)}</span>`;
  const rsiCls = r.rsi_state === "Ipervenduto" ? "good" : r.rsi_state === "Ipercomprato" ? "bad" : "mid";
  return `<tr data-t="${esc(r.t)}">
    <td class="num">${r.rank ?? "–"}</td>
    <td><div class="tk">${esc(r.t)} ${badges(r)}</div><div class="nm">${esc(r.n)}</div><div class="sec">${esc(r.industry)}${r.ciclico ? " · ciclico" : ""}</div></td>
    <td class="num score">${ok(r.score) ? r.score.toFixed(1) : "–"}</td>
    <td class="hide-s"><div class="bar">${bar}</div></td>
    <td>${flag}</td>
    <td class="num hide-s">${cmpCell(r.k1, "high")}</td>
    <td class="num hide-s">${cmpCell(r.k2, "low")}</td>
    <td class="hide-m">${r.rsi_state ? `<span class="pill ${rsiCls}">${fmt(r.rsi, "n1")} · ${r.rsi_state}</span>` : "n.d."}</td>
    <td class="num hide-m">${money(r.mcap, "$")}</td>
  </tr>`;
}

// ------------------------------------------------------------------ scheda titolo

function fromHash() {
  const t = decodeURIComponent(location.hash.slice(1));
  if (t) open(t, false); else close(false);
}

async function open(t, push = true) {
  if (push) { history.replaceState(null, "", "#" + encodeURIComponent(t)); }
  const file = "data/stocks/" + t.replace(/\//g, "_").replace(/\^/g, "_") + ".json";
  $("#card").innerHTML = `<p class="note">Caricamento…</p>`;
  $("#drawer").classList.add("on"); $("#scrim").classList.add("on");
  try {
    const s = await (await fetch(file, { cache: "no-store" })).json();
    $("#card").innerHTML = card(s);
    $("#card .close").addEventListener("click", () => close());
    $("#drawer").scrollTop = 0;
  } catch (e) {
    $("#card").innerHTML = `<p class="note">Scheda non disponibile.</p>`;
  }
}
function close(push = true) {
  $("#drawer").classList.remove("on"); $("#scrim").classList.remove("on");
  if (push && location.hash) history.replaceState(null, "", location.pathname);
}

function compRows(s, areas) {
  const comps = Object.values(s.components || {}).filter((c) => areas.includes(c.area));
  if (!comps.length) return "";
  const head = `<div class="mrow h"><span>Indicatore</span><span class="r">Azienda</span><span class="r">Mediana</span><span class="r">Percentile</span></div>`;
  return head + comps.map((c) => {
    const [label, f] = L[c.metric] || [c.metric, "n2"];
    const med = s.peer_medians ? s.peer_medians[c.metric] : null;
    const vd = verdict(c.value, med, c.dir);
    const p = ok(c.pct) ? Math.round(c.pct * 100) : null;
    return `<div class="mrow"><span>${label} <span class="note">· ${c.points} pt</span></span>
      <span class="r ${ok(med) ? vd + "-t" : ""}">${fmt(c.value, f)}</span>
      <span class="r" style="color:var(--ink-3)">${ok(med) ? fmt(med, f) : "–"}</span>
      <span>${p === null ? `<span class="note">n.d.</span>` : `<div class="pbar" title="percentile ${p}"><i style="width:${p}%"></i></div>`}</span></div>`;
  }).join("");
}

function block(title, color, pts, max, body) {
  const p = max === null ? "" : ok(pts) ? `${pts.toFixed(1)} / ${max}` : `– / ${max}`;
  return `<section class="block"><h3><span><span class="tag" style="background:${color}"></span>${title}</span><span class="pts">${p}</span></h3>${body}</section>`;
}
const frag = (parts) => `<p class="frag">${parts.filter(Boolean).join('<span class="sep">•</span>')}</p>`;
const kv = (k, v) => `<span class="k">${k}:</span> ${v}`;

function card(s) {
  const m = s.metrics || {}, info = s.info || {}, g = s.governance || {}, w = { nucleo: 30, valutazione: 20, moat: 20, macro: 15, protezione: 10, tecnica: 5 };
  const a = s.areas || {};
  const fin = s.track === "banca" || s.track === "assicurazione";
  const ccy = m.trading_currency || info.currency || "";
  const sccy = m.statement_currency || "";

  const areasHtml = AREAS.map(([k, l, c]) => {
    const v = a[k], pct = ok(v) ? (v / w[k]) * 100 : 0;
    return `<div class="area"><div class="l">${l}</div><div class="v">${ok(v) ? v.toFixed(1) : "–"}<span class="note">/${w[k]}</span></div><div class="track"><i style="width:${pct}%;background:${c}"></i></div></div>`;
  }).join("");

  const flags = s.flags && s.flags.length
    ? `<div class="flags"><b>${s.status === "escluso" ? "Escluso dalla classifica" : esc(s.status)}</b><ul>${s.flags.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>` : "";

  // ---- blocco 1
  const lab = { m: s.metrics };
  const ms = m.beneish_m, z = m.altman_z;
  const msState = !ok(ms) ? "n.d." : ms < -1.78 ? `<span class="good-t">Sano</span>` : `<span class="bad-t">Allarme</span>`;
  const zState = !ok(z) ? "n.d." : z > 2.99 ? `<span class="good-t">Sicuro</span>` : z >= 1.81 ? `<span class="mid-t">Zona grigia</span>` : `<span class="bad-t">Distress</span>`;
  const adv = m.avg_daily_value_usd;
  const liq = ok(adv) ? (adv >= 2e6 ? `<span class="good-t">Idoneo</span>` : `<span class="bad-t">Illiquido</span>`) : "n.d.";
  const ceo = g.ceo;
  const ins = g.insider_6m;
  let insTxt = "n.d.";
  if (ins && ok(ins.net_shares)) insTxt = ins.net_shares > 0 ? `<span class="good-t">🟢 Net buying</span>` : ins.net_shares < 0 ? `<span class="bad-t">🔴 Net selling</span>` : "Neutro";
  const top3 = (g.top_institutions || []).map((h) => `${esc(h.name)}${ok(h.pct) ? ` (${fmt(h.pct, "pct")})` : ""}`).join(" · ");
  const ff = m.free_float;
  const b1 = [
    frag([`<b>${esc(s.name)}</b>`, `<span class="mono">${esc(s.ticker)}</span>`, esc(info.sector), esc(info.industry),
      TRACKS[s.track] + (s.ciclico ? " · ciclico" : "")]),
    frag([kv("Prezzo", `<span class="mono">${ok(m.price) ? m.price.toFixed(2) : "n.d."} ${esc(ccy)}</span>`),
      kv("Mkt cap", money(m.market_cap_usd, "$")), kv("Indice", esc(s.index)), info.country ? kv("Paese", esc(info.country)) : ""]),
    !fin ? frag([`🛡️ ${kv("M-Score", `<span class="mono">${fmt(ms, "n2")}</span>`)}`, "Soglia &lt; −1.78", msState]) : "",
    !fin ? frag([kv("Altman Z", `<span class="mono">${fmt(z, "n2")}</span>`), "Soglia &gt; 2.99", zState]) : "",
    frag([kv("Volume medio 3M", ok(m.avg_volume_3m) ? Math.round(m.avg_volume_3m).toLocaleString("it-IT") + " az." : "n.d."),
      kv("Controvalore", money(adv, "$") + "/g"), liq]),
    frag([`👤 ${kv("CEO", ceo ? esc(ceo.name) : "n.d.")}`, ceo && ceo.age ? `${ceo.age} anni` : "",
      kv("Quote insider", fmt(info.heldPercentInsiders, "pct")), kv("Insider 6M", insTxt)]),
    frag([`🏛️ ${kv("Istituzionali", fmt(info.heldPercentInstitutions, "pct"))}`, top3 ? kv("Top 3", top3) : "",
      kv("Flottante", ok(ff) ? fmt(ff, "pct") + (ff < 0.2 ? ` <span class="bad-t">(controllo concentrato)</span>` : "") : "n.d.")]),
    compRows(s, ["protezione"]),
  ].join("");

  // ---- blocco 2
  const ser = m.series || {};
  const yrs = ser.fy || [];
  const hrow = (lbl, arr, f) => `<tr><td>${lbl}</td>${(arr || []).map((v) => `<td>${f === "pct" ? fmt(v, "pct") : money(v)}</td>`).join("")}</tr>`;
  const histTbl = yrs.length ? `<table class="hist"><tr><th>${esc(sccy)}</th>${yrs.map((y) => `<th>${y}</th>`).join("")}</tr>
    ${hrow("Ricavi", ser.revenue)}${!fin ? hrow("EBITDA", ser.ebitda) : ""}${hrow("Utile netto", ser.net_income)}
    ${!fin ? hrow("Free cash flow", ser.fcf) : ""}${fin ? hrow("ROE", ser.roe, "pct") : hrow("ROIC", ser.roic, "pct")}</table>` : "";
  const b2 = compRows(s, ["nucleo"]) + histTbl;

  // ---- blocco 3
  let mos = "";
  if (fin && ok(m.ptbv) && ok(m.ptbv_theoretical)) {
    const d = 1 - m.ptbv / m.ptbv_theoretical;
    mos = frag([kv("P/TBV", `<span class="mono">${fmt(m.ptbv, "x2")}</span>`), `teorico ${fmt(m.ptbv_theoretical, "x2")} (ROTE ${fmt(m.rote_avg3, "pct")} / costo capitale 10%)`,
      `<span class="${d > 0 ? "good" : "bad"}-t">${d > 0 ? "Sconto" : "Premio"} ${fmt(Math.abs(d), "pct")}</span>`]);
  } else if (ok(m.ev_ebitda) && s.peer_medians && ok(s.peer_medians.ev_ebitda)) {
    const d = 1 - m.ev_ebitda / s.peer_medians.ev_ebitda;
    mos = frag([kv("EV/EBITDA", `<span class="mono">${fmt(m.ev_ebitda, "x")}</span>`), `mediana settore ${fmt(s.peer_medians.ev_ebitda, "x")}`,
      `<span class="${d > 0 ? "good" : "bad"}-t">${d > 0 ? "Sconto" : "Premio"} ${fmt(Math.abs(d), "pct")}</span>`]);
  }
  const histMult = !fin && ok(m.ev_ebitda_hist_avg) ? frag([kv("Media storica EV/EBITDA", fmt(m.ev_ebitda_hist_avg, "x")), kv("Attuale", fmt(m.ev_ebitda, "x"))]) : "";
  const b3 = mos + histMult + (!fin ? frag([kv("FCF yield", fmt(m.fcf_yield, "pct"))]) : "") + compRows(s, ["valutazione"]);

  // ---- blocco 4
  const stab = (v) => !ok(v) ? "n.d." : -v < 0.15 ? `<span class="good-t">Alta</span>` : -v < 0.35 ? `<span class="mid-t">Media</span>` : `<span class="bad-t">Bassa</span>`;
  const pg = s.peer_revenue_cagr;
  const wind = !ok(pg) ? "" : pg > 0.08 ? "settore in forte espansione" : pg > 0.03 ? "settore in crescita" : pg > -0.01 ? "settore stabile" : "settore in contrazione";
  const peerName = (s.peer_group || "").split("|").slice(2).join("") || "intero percorso";
  const b4 = frag([kv(fin ? "Stabilità ROE 5 anni" : "Stabilità ROIC 5 anni", stab(fin ? m.roe_stability : m.roic_stability)),
      !fin && ok(m.gross_margin_std) ? kv("Dev. std margine lordo", fmt(m.gross_margin_std * 100, "n1") + " pp") : ""])
    + frag([kv("Vento a favore", `CAGR ricavi settore ${fmt(pg, "pct")}`), wind ? `<b>${wind}</b>` : "",
      kv("Comparabili", `${esc(peerName)} (${s.peer_n ?? "–"} titoli)`)])
    + compRows(s, ["moat", "macro"]);

  // ---- blocco 5
  const rsi = m.rsi14;
  const rsiS = !ok(rsi) ? "" : rsi > 70 ? `<span class="bad-t">Ipercomprato</span>` : rsi < 30 ? `<span class="good-t">Ipervenduto</span>` : "Neutrale";
  const ext = m.dist_sma200;
  const b5 = frag([kv("RSI 14g", `<span class="mono">${fmt(rsi, "n1")}</span>`), rsiS])
    + frag([kv("Distanza SMA200", fmt(ext, "pct")), ok(ext) && ext > 0.25 ? `<span class="bad-t">Surriscaldato</span>` : "",
      kv("SMA50", ok(m.sma50) ? m.sma50.toFixed(2) : "n.d."), kv("SMA200", ok(m.sma200) ? m.sma200.toFixed(2) : "n.d.")])
    + frag([kv("Short interest", fmt(m.short_pct_float, "pct")), ok(m.short_pct_float) && m.short_pct_float > 0.15 ? `<span class="bad-t">Allarme</span>` : "",
      kv("Min/Max 52 sett.", ok(m.low_52w) ? `${m.low_52w.toFixed(2)} – ${m.high_52w.toFixed(2)}` : "n.d.")])
    + compRows(s, ["tecnica"]);

  const src = Object.values(s.sources || {});
  const srcTxt = src.includes("sec") ? "SEC EDGAR + Yahoo Finance" : "Yahoo Finance";
  const cover = ok(s.coverage) ? `Copertura dati del punteggio ${Math.round(s.coverage * 100)}%` : "";

  // ---- segnali, controprova, settore, analisti
  const ex = s.exit || [];
  const dq = s.data_quality || {};
  const dqLab = { verificato: `<span class="good-t">✓ Verificato</span>`, discordante: `<span class="bad-t">✗ Discordante</span>`, "non verificato": `<span class="mid-t">Non verificato</span>`, "principi diversi": `<span class="mid-t">≈ Principi contabili diversi</span>` }[dq.status] || "n.d.";
  const dqItems = Object.entries(dq.items || {}).map(([k, it]) => {
    const lab = { total_assets: "Attivo", equity: "Patrimonio netto", net_income: "Utile netto", revenue: "Ricavi" }[k] || k;
    return `<div class="mrow"><span>${lab}</span><span class="r">${money(it.yahoo)}</span><span class="r">${money(it.official)}</span><span class="r ${it.diff > 0.1 ? "bad-t" : "good-t"}">${ok(it.diff) ? (it.diff * 100).toFixed(1) + "%" : "–"}</span></div>`;
  }).join("");
  const dqTbl = dqItems ? `<div class="mrow h"><span>Voce (esercizio ${esc(dq.fy_end || "")})</span><span class="r">Yahoo</span><span class="r">${esc(dq.source || "Ufficiale")}</span><span class="r">Scarto</span></div>${dqItems}` : "";
  const st = s.sector_trend || {};
  const um = state.meta ? state.meta.universe_ret_12m : null;
  const unusual = m.unusual_items_last;
  const adjTxt = ok(unusual) && Math.abs(unusual) > 0 ? frag([kv("Voci straordinarie ultimo esercizio", money(unusual, sccy)), kv("Utile riportato", money(m.net_income_reported, sccy)), kv("Utile rettificato", money(m.net_income_adjusted, sccy))]) : "";
  const tgt = info.targetMeanPrice;
  const up = ok(tgt) && ok(m.price) ? tgt / m.price - 1 : null;
  const analyst = ok(tgt) || info.recommendationKey ? frag([kv("Analisti", `${info.numberOfAnalystOpinions ?? "n.d."}`), kv("Prezzo obiettivo medio", ok(tgt) ? `${tgt.toFixed(2)} ${esc(ccy)}` : "n.d."),
      ok(up) ? `<span class="${up >= 0 ? "good" : "bad"}-t">${up >= 0 ? "+" : ""}${(up * 100).toFixed(1)}%</span>` : "",
      ok(info.targetLowPrice) ? kv("Range", `${info.targetLowPrice.toFixed(2)} – ${info.targetHighPrice.toFixed(2)}`) : "",
      info.recommendationKey ? kv("Giudizio", esc(info.recommendationKey)) : "", ok(info.forwardPE) ? kv("P/E atteso", fmt(info.forwardPE, "x")) : ""]) : "";
  const b0 = (ex.length ? `<div class="flags ${ex.some((e) => e.startsWith("Esci")) ? "" : "warn"}"><b>Segnali</b><ul>${ex.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : `<p class="frag"><span class="good-t">Nessun segnale di uscita</span></p>`)
    + (s.value_trap ? `<p class="frag"><span class="bad-t">⚠ Possibile value trap:</span> ${esc(s.value_trap)}</p>` : "")
    + frag([kv("Gruppo", esc(s.bucket || "n.d.")), ok(s.pf_weight) ? kv("Portafoglio modello", `<b>${(s.pf_weight * 100).toFixed(1)}%</b>`) : kv("Portafoglio modello", "no")])
    + frag([kv("Titolo 12 mesi", fmt(st.own_ret_12m, "pct")), kv("Settore 12 mesi", fmt(st.peer_ret_12m, "pct")), kv("Universo 12 mesi", fmt(um, "pct"))])
    + frag([kv("Controprova dati", dqLab), dq.source ? kv("Fonte", esc(dq.source)) : ""]) + dqTbl
    + (dq.notes || []).map((n) => `<p class="note">• ${esc(n)}</p>`).join("")
    + adjTxt
    + (analyst ? analyst + `<p class="note">Stime degli analisti: solo informative, non entrano nel punteggio.</p>` : "");

  return `<div class="d-head"><div><h2>${esc(s.name)}</h2><div class="tk">${esc(s.ticker)} · ${esc(info.sector || "")} · ${esc(s.region)}</div></div>
      <button class="close" aria-label="Chiudi">×</button></div>
    <div class="d-score"><div class="big">${ok(s.score) ? s.score.toFixed(1) : "–"}<small> /100</small></div>
      <div>${s.rank ? `<span class="pill good">#${s.rank} in classifica</span>` : `<span class="pill ${s.status === "escluso" ? "bad" : "mid"}">${esc(s.status)}</span>`}</div></div>
    <div class="areas">${areasHtml}</div>
    ${flags}
    ${block("Segnali &amp; controlli", "var(--ink-3)", null, null, b0)}
    ${block("Identità, governance &amp; sopravvivenza", "var(--a5)", a.protezione, 10, b1)}
    ${block("Il nucleo operativo", "var(--a1)", a.nucleo, 30, b2)}
    ${block("Valutazione &amp; margine di sicurezza", "var(--a2)", a.valutazione, 20, b3)}
    ${block("Moat &amp; macro", "var(--a3)", (a.moat ?? 0) + (a.macro ?? 0), 35, b4)}
    ${block("Tecnica &amp; psicologia", "var(--a6)", a.tecnica, 5, b5)}
    <p class="note">Bilanci: ${srcTxt} · ultimo esercizio ${esc(m.fy_last || "n.d.")} · valuta di bilancio ${esc(sccy)} · ${cover} · bilanci scaricati ${esc((s.fetched_at || "").slice(0, 10))}</p>`;
}

init().catch((e) => { $("#meta").textContent = "Dati non disponibili: " + e.message; });
