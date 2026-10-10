"""Controlli e decisioni sopra il punteggio: qualità dei dati, value trap, segnali di uscita,
gruppi Conviction/Cyclical/Protective e portafoglio modello."""
from __future__ import annotations

import math

import pandas as pd


def _n(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


# ------------------------------------------------------------------ qualità dei dati

def data_quality(rec: dict, cfg: dict) -> dict:
    """Confronto con la fonte ufficiale + controlli di coerenza interna."""
    dc = cfg["data_check"]
    cc = rec.get("crosscheck") or {}
    items = cc.get("items") or {}
    years = rec.get("years") or []
    last = years[-1] if years else {}
    assets = _n(last.get("total_assets")) or 0

    discord, compared = [], 0
    for k, tol in dc["tolerance"].items():
        it = items.get(k)
        if not it or it.get("diff") is None:
            continue
        if k == "net_income" and assets and abs(it["official"]) < dc["min_abs_net_income_share"] * assets:
            continue  # utile troppo piccolo per un confronto percentuale significativo
        compared += 1
        if it["diff"] > tol:
            discord.append(f"{k}: Yahoo {it['yahoo']:,.0f} vs ufficiale {it['official']:,.0f} ({it['diff']:.0%})")

    notes = []
    tl, eq = _n(last.get("total_liabilities")), _n(last.get("equity"))
    if assets and tl is not None and eq is not None and abs(assets - tl - eq) / assets > 0.15:
        notes.append("Attivo diverso da passivo + patrimonio di oltre il 15% (possibili quote di terzi)")
    rev = [_n(y.get("revenue")) for y in years[-2:]]
    if len(rev) == 2 and rev[0] and rev[1] and rev[0] > 0:
        g = rev[1] / rev[0] - 1
        if g > 2 or g < -0.7:
            notes.append(f"Variazione ricavi anomala nell'ultimo anno ({g:+.0%}): verificare operazioni straordinarie")

    rev_it = items.get("revenue")
    same_revenue = rev_it is not None and rev_it.get("diff") is not None and rev_it["diff"] <= 0.02
    if discord and same_revenue:
        # ricavi identici ma patrimonio/utile diversi: tipico di principi contabili diversi
        # (es. US GAAP su Yahoo e IFRS nel bilancio europeo), non di un errore nei dati
        notes.append("Ricavi identici alla fonte ufficiale; le differenze su "
                     + ", ".join(d.split(":")[0] for d in discord)
                     + " indicano principi contabili diversi (es. US GAAP vs IFRS)")
        discord = []
    if discord:
        status = "discordante"
    elif same_revenue and any(n.startswith("Ricavi identici") for n in notes):
        status = "principi diversi"
    elif compared >= 2:
        status = "verificato"
    else:
        status = "non verificato"
    return {"status": status, "source": cc.get("source"), "fy_end": cc.get("fy_end"),
            "compared": compared, "discordances": discord, "notes": notes, "items": items}


# ------------------------------------------------------------------ value trap

def value_trap(r: dict, areas: dict, cfg: dict, universe_med_12m) -> tuple[bool, str | None]:
    vt = cfg["value_trap"]
    w = cfg["area_weights"]["valutazione"]
    val = areas.get("valutazione")
    if val is None or val < vt["cheap_min_share"] * w:
        return False, None
    worse = []
    if _n(r.get("revenue_cagr")) is not None and r["revenue_cagr"] < 0:
        worse.append(f"ricavi in calo ({r['revenue_cagr']:+.1%} annuo)")
    if _n(r.get("net_income_cagr")) is not None and r["net_income_cagr"] < 0:
        worse.append(f"utile in calo ({r['net_income_cagr']:+.1%} annuo)")
    if not worse:
        return False, None
    sec = _n(r.get("peer_price_12m"))
    if sec is None or universe_med_12m is None or sec >= universe_med_12m - vt["sector_lag"]:
        return False, None
    return True, (f"Economico ma {', '.join(worse)} e settore debole sul mercato "
                  f"({sec:+.1%} a 12 mesi vs {universe_med_12m:+.1%} dell'universo)")


# ------------------------------------------------------------------ segnali di uscita

def exit_signals(r: dict, status: str, flags: list, med: dict, prev: dict | None, vt_reason, cfg: dict) -> list[str]:
    ex = cfg["exit_rules"]
    out = []
    if status == "escluso":
        out.append("Esci: red flag attiva (" + "; ".join(flags) + ")")
    elif status not in ("classificato",):
        out.append(f"Rivaluta: {status}")
    rank = _n(r.get("rank"))
    if status == "classificato" and rank and rank > ex["out_of_top"]:
        out.append(f"Rivaluta: fuori dalle prime {ex['out_of_top']} (posizione {int(rank)})")
    if prev and _n(r.get("score")) is not None and _n(prev.get("score")) is not None:
        drop = prev["score"] - r["score"]
        if drop >= ex["score_drop"]:
            out.append(f"Rivaluta: punteggio sceso di {drop:.1f} punti dal {prev.get('date')}")
    if ex["discount_exhausted"]:
        if r.get("track") in ("banca", "assicurazione"):
            g = _n(r.get("ptbv_gap"))
            if g is not None and g >= 1:
                out.append(f"Sconto esaurito: P/TBV al {g:.0%} del valore teorico")
        elif r.get("track") == "reit":
            v, m = _n(r.get("p_ffo")), _n(med.get("p_ffo"))
            if v and m and v >= m:
                out.append(f"Sconto esaurito: P/FFO {v:.1f}x ≥ mediana {m:.1f}x")
        else:
            v, m = _n(r.get("ev_ebitda")), _n(med.get("ev_ebitda"))
            if v and m and v >= m:
                out.append(f"Sconto esaurito: EV/EBITDA {v:.1f}x ≥ mediana settore {m:.1f}x")
    if vt_reason:
        out.append("Attenzione: possibile value trap")
    return out


# ------------------------------------------------------------------ gruppi e portafoglio

def bucket(r: dict, cfg: dict) -> str:
    p = cfg["portfolio"]
    if r.get("ciclico") or r.get("sector") in p["cyclical_sectors"] or r.get("track") in p["cyclical_tracks"]:
        return "cyclical"
    if r.get("sector") in p["protective_sectors"]:
        return "protective"
    return "conviction"


def build_portfolio(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Selezione dalla classifica rispettando gruppi, limiti per settore e per paese."""
    p = cfg["portfolio"]
    cand = df[(df["status"] == "classificato") & (df["coverage"].fillna(0) >= p["min_coverage"])]
    if cfg["value_trap"]["exclude_from_portfolio"]:
        cand = cand[~cand["value_trap"].fillna(False)]
    cand = cand.sort_values("rank")
    total = sum(b["positions"] for b in p["buckets"].values())
    max_country = max(1, int(p["max_country_share"] * total))
    picked, per_sector, per_country = [], {}, {}
    per_bucket = {b: 0 for b in p["buckets"]}
    for _, r in cand.iterrows():
        b = r["bucket"]
        if per_bucket.get(b, 0) >= p["buckets"][b]["positions"]:
            continue
        if per_sector.get(r["sector"], 0) >= p["max_per_sector"]:
            continue
        ctry = r["country"] if isinstance(r["country"], str) and r["country"] else r["region"]
        if per_country.get(ctry, 0) >= max_country:
            continue
        picked.append(r["ticker"])
        per_bucket[b] += 1
        per_sector[r["sector"]] = per_sector.get(r["sector"], 0) + 1
        per_country[ctry] = per_country.get(ctry, 0) + 1
        if len(picked) >= total:
            break
    out = df[df["ticker"].isin(picked)].copy()
    # peso: quota del gruppo divisa per i titoli scelti nel gruppo (si ridistribuisce se un gruppo è incompleto)
    filled = {b: n for b, n in per_bucket.items() if n}
    wsum = sum(p["buckets"][b]["weight"] for b in filled) or 1
    out["pf_weight"] = [p["buckets"][b]["weight"] / wsum / filled[b] for b in out["bucket"]]
    return out.sort_values(["bucket", "rank"])
