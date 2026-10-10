"""Punteggio su 100, red flag, classifica ed esportazione dei dati per la dashboard."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .common import DATA, FUND_DIR, SITE_DATA, load_config, log, read_json, safe_name, write_json
from .metrics import FX, compute, technicals
from .overlay import build_portfolio, bucket, data_quality, exit_signals, value_trap

AREA_LABELS = {"nucleo": "Nucleo", "valutazione": "Valutazione", "moat": "Moat",
               "macro": "Macro/TAM", "protezione": "Protezione", "tecnica": "Tecnica"}

# metriche confrontate con l'intero universo e non con i comparabili di settore
UNIVERSE_RANKED = {"rsi14", "dist_sma200", "short_pct_float", "peer_revenue_cagr", "peer_growth_consistency"}

# metriche di cui mostrare la mediana di settore nella scheda
DISPLAY_MEDIANS = ["roic", "roic_avg", "fcf_margin", "net_margin", "gross_margin", "gross_margin_avg",
                   "net_debt_to_ebitda", "interest_coverage", "debt_to_equity", "ev_ebitda", "pe", "p_fcf",
                   "pb", "revenue_cagr", "roe", "roe_avg", "cost_income", "ptbv", "equity_to_assets",
                   "p_ffo", "ffo_margin", "ebitda_margin_avg", "debt_to_assets", "fcf_yield"]


# ------------------------------------------------------------------ caricamento

def _load_prices():
    daily = pd.read_parquet(DATA / "prices_daily.parquet") if (DATA / "prices_daily.parquet").exists() else None
    weekly = pd.read_parquet(DATA / "prices_weekly.parquet") if (DATA / "prices_weekly.parquet").exists() else None
    fxw = pd.read_parquet(DATA / "fx_weekly.parquet") if (DATA / "fx_weekly.parquet").exists() else None
    d_groups = {t: g.set_index("date").sort_index() for t, g in daily.groupby("ticker")} if daily is not None else {}
    w_groups = {t: g.set_index("date")["Close"].sort_index() for t, g in weekly.groupby("ticker")} if weekly is not None else {}
    return d_groups, w_groups, FX(fxw)


def _track(info: dict, cfg: dict, revenue_usd) -> tuple[str, bool]:
    tr = cfg["tracks"]
    ind = info.get("industry") or ""
    if not ind and not info.get("sector"):
        return "escluso_nosettore", False
    if any(ind.startswith(p) for p in tr["banca_industry_prefix"]):
        return "banca", False
    if any(ind.startswith(p) for p in tr["assicurazione_industry_prefix"]):
        return "assicurazione", False
    if any(ind.startswith(p) for p in tr["reit_industry_prefix"]):
        return "reit", False
    ex = tr["esclusi"]
    if ind in ex["biotech_industries"] and (revenue_usd or 0) < ex["biotech_min_revenue_usd"]:
        return "escluso_biotech", False
    return "usuale", ind in tr["ciclici_industries"]


# ------------------------------------------------------------------ red flag

def _red_flags(track: str, m: dict, info: dict, cfg: dict) -> list[str]:
    rf = cfg["red_flags"]
    flags = []
    adv = m.get("avg_daily_value_usd")
    if adv is not None and adv < rf["comuni"]["min_avg_daily_value_usd"]:
        flags.append(f"Liquidità insufficiente ({adv / 1e6:.1f} M$/giorno)")
    if track == "usuale":
        r = rf["usuale"]
        if m.get("beneish_m") is not None and m["beneish_m"] > r["beneish_m_max"]:
            flags.append(f"Beneish M-Score {m['beneish_m']:.2f} > {r['beneish_m_max']}")
        if m.get("debt_to_equity") is not None and m["debt_to_equity"] > r["debt_to_equity_max"]:
            flags.append(f"Debt/Equity {m['debt_to_equity']:.2f} > {r['debt_to_equity_max']}")
        if m.get("net_debt_to_ebitda") is not None and m["net_debt_to_ebitda"] > r["net_debt_to_ebitda_max"]:
            flags.append(f"PFN/EBITDA {m['net_debt_to_ebitda']:.1f}x > {r['net_debt_to_ebitda_max']}x")
        if m.get("interest_coverage") is not None and m["interest_coverage"] < r["interest_coverage_min"]:
            flags.append(f"Copertura interessi {m['interest_coverage']:.1f}x < {r['interest_coverage_min']}x")
        if m.get("gross_margin") is not None and m["gross_margin"] < r["gross_margin_min"]:
            flags.append(f"Margine lordo {m['gross_margin']:.1%} < {r['gross_margin_min']:.0%}")
        if m.get("roic_avg") is not None and m["roic_avg"] < r["roic_min"]:
            flags.append(f"ROIC medio {m['roic_avg']:.1%} < {r['roic_min']:.0%}")
        if (m.get("altman_z") is not None and m["altman_z"] < r["altman_z_min"]
                and (info.get("sector") or "") not in r["altman_exempt_sectors"]):
            flags.append(f"Altman Z {m['altman_z']:.2f} in zona di distress (< {r['altman_z_min']})")
    elif track in ("banca", "assicurazione"):
        r = rf[track]
        if m.get("equity_to_assets") is not None and m["equity_to_assets"] < r["equity_to_assets_min"]:
            flags.append(f"Patrimonio/attivo {m['equity_to_assets']:.1%} < {r['equity_to_assets_min']:.0%}")
        if r.get("last_year_loss") and m.get("last_year_loss"):
            flags.append("Perdita nell'ultimo esercizio")
    elif track == "reit":
        r = rf["reit"]
        if m.get("net_debt_to_ebitda") is not None and m["net_debt_to_ebitda"] > r["net_debt_to_ebitda_max"]:
            flags.append(f"PFN/EBITDA {m['net_debt_to_ebitda']:.1f}x > {r['net_debt_to_ebitda_max']}x")
        if m.get("interest_coverage") is not None and m["interest_coverage"] < r["interest_coverage_min"]:
            flags.append(f"Copertura interessi {m['interest_coverage']:.1f}x < {r['interest_coverage_min']}x")
    return flags


# ------------------------------------------------------------------ comparabili

def _peer_groups(df: pd.DataFrame, min_peers: int) -> pd.Series:
    """Industria se ha abbastanza titoli nel percorso, altrimenti settore, altrimenti tutto il percorso."""
    ind_n = df.groupby(["track", "industry"])["ticker"].transform("count")
    sec_n = df.groupby(["track", "sector"])["ticker"].transform("count")
    return np.where(ind_n >= min_peers, df["track"] + "|ind|" + df["industry"].fillna("?"),
                    np.where(sec_n >= min_peers, df["track"] + "|sec|" + df["sector"].fillna("?"),
                             df["track"] + "|all"))


def _peer_dynamics(df: pd.DataFrame, by_year: dict) -> pd.DataFrame:
    """Crescita mediana del gruppo, costanza della crescita, persistenza ROIC/ROE sopra la mediana."""
    out = []
    for g, sub in df.groupby("peer_group"):
        tick = sub["ticker"].tolist()
        rev_cagr = sub["revenue_cagr"].median()
        # crescita annua mediana del gruppo
        yr_growth: dict[str, list] = {}
        for t in tick:
            for y, v in (by_year[t]["growth"] or {}).items():
                yr_growth.setdefault(y, []).append(v)
        med_g = {y: float(np.median(v)) for y, v in yr_growth.items() if len(v) >= 3}
        consistency = (sum(1 for v in med_g.values() if v > 0) / len(med_g)) if len(med_g) >= 2 else None
        # mediane annue di ROIC e ROE
        med = {}
        for key in ("roic", "roe"):
            vals: dict[str, list] = {}
            for t in tick:
                for y, v in (by_year[t][key] or {}).items():
                    if v is not None:
                        vals.setdefault(y, []).append(v)
            med[key] = {y: float(np.median(v)) for y, v in vals.items() if len(v) >= 3}
        for t in tick:
            row = {"ticker": t, "peer_revenue_cagr": rev_cagr, "peer_growth_consistency": consistency,
                   "peer_growth_by_year": med_g}
            for key in ("roic", "roe"):
                own = {y: v for y, v in (by_year[t][key] or {}).items() if v is not None and y in med[key]}
                row[f"{key}_above_peer_share"] = (sum(1 for y, v in own.items() if v > med[key][y]) / len(own)
                                                  if len(own) >= 3 else None)
            out.append(row)
    return pd.DataFrame(out)


def _pct(series: pd.Series, direction: str) -> pd.Series:
    s = series.astype(float)
    if direction == "low":
        s = -s
    n = s.notna().sum()
    if n == 0:
        return s * np.nan
    if n == 1:
        return s.where(s.isna(), 0.5)
    r = s.rank(method="average")
    return (r - 1) / (n - 1)


# ------------------------------------------------------------------ punteggio

def score_all() -> None:
    cfg = load_config()
    gen = cfg["general"]
    weights = cfg["area_weights"]
    universe = pd.read_csv(DATA / "universe.csv")
    d_groups, w_groups, fx = _load_prices()

    rows, details, by_year = [], {}, {}
    for _, u in universe.iterrows():
        t = u.ticker
        rec = read_json(FUND_DIR / f"{safe_name(t)}.json")
        base = {"ticker": t, "region": u.region, "index": u["index"], "country": u.country}
        if not rec or rec.get("skip"):
            continue
        info = rec.get("info", {})
        d = d_groups.get(t)
        tech = technicals(d["Close"], d.get("Volume")) if d is not None else {}
        m = compute(rec, tech, w_groups.get(t), fx, cfg)
        track, ciclico = _track(info, cfg, m.get("revenue_usd"))
        row = {**base, **{k: v for k, v in m.items() if not isinstance(v, (dict, list))},
               "name": info.get("longName") or info.get("shortName") or t,
               "sector": info.get("sector") or "N/D", "industry": info.get("industry") or "N/D",
               "track": track, "ciclico": ciclico, "country_name": info.get("country")}
        rows.append(row)
        by_year[t] = {"growth": m.get("revenue_growth_by_year"), "roic": m.get("roic_by_year"),
                      "roe": m.get("roe_by_year")}
        details[t] = {"rec": rec, "metrics": m}

    df = pd.DataFrame(rows)
    if df.empty:
        log.error("Nessun titolo con dati: niente da classificare")
        return
    scorable_tracks = ["usuale", "banca", "assicurazione", "reit"]
    df["peer_group"] = None
    mask = df["track"].isin(scorable_tracks)
    df.loc[mask, "peer_group"] = _peer_groups(df[mask], gen["min_peers"])
    dyn = _peer_dynamics(df[mask], by_year)
    df = df.merge(dyn, on="ticker", how="left")
    df["share_gain"] = df["revenue_cagr"] - df["peer_revenue_cagr"]
    if "ret_12m" not in df.columns:
        df["ret_12m"] = np.nan
    df["peer_price_12m"] = df.groupby("peer_group")["ret_12m"].transform("median")
    universe_med_12m = df.loc[mask, "ret_12m"].median()
    universe_med_12m = None if pd.isna(universe_med_12m) else float(universe_med_12m)

    # percentili per componente
    comp_pct: dict[str, pd.Series] = {}
    for track in scorable_tracks:
        tmask = df["track"] == track
        for area, comps in cfg["components"][track].items():
            for metric, spec in comps.items():
                if metric not in df.columns:
                    df[metric] = np.nan
                key = f"{track}:{metric}"
                if metric in UNIVERSE_RANKED:
                    pct = _pct(df.loc[tmask, metric], spec["dir"])
                else:
                    pct = df.loc[tmask].groupby("peer_group")[metric].transform(lambda s, d=spec["dir"]: _pct(s, d))
                comp_pct[key] = pct

    # mediane di settore da mostrare
    med_keys = set(DISPLAY_MEDIANS)
    for tr in scorable_tracks:
        for comps in cfg["components"][tr].values():
            med_keys |= set(comps)
    med_keys -= UNIVERSE_RANKED | {"share_gain"}
    medians = {}
    for g, sub in df[mask].groupby("peer_group"):
        medians[g] = {k: (float(sub[k].median()) if k in sub and sub[k].notna().sum() >= 3 else None)
                      for k in med_keys}
        medians[g]["n"] = len(sub)

    results = []
    for i, r in df.iterrows():
        t = r.ticker
        track = r.track
        res = {"areas": {}, "components": {}, "flags": [], "status": "classificato", "coverage": None}
        if track not in scorable_tracks:
            res["status"] = "fuori modello"
            res["flags"] = (["Biotech senza ricavi significativi: valore legato ai trial clinici"]
                            if track == "escluso_biotech" else
                            ["Nessuna classificazione settoriale (fondo chiuso o veicolo d'investimento)"])
        elif (0 if pd.isna(r.n_years) else r.n_years) < gen["min_years_scored"]:
            ny = 0 if pd.isna(r.n_years) else int(r.n_years)
            res["status"] = "storico insufficiente"
            res["flags"] = [f"Solo {ny} esercizi disponibili (minimo {gen['min_years_scored']})"]
        elif r.fy_last is None or pd.isna(r.fy_last) or (pd.Timestamp.now() - pd.Timestamp(r.fy_last)).days > 550:
            res["status"] = "dati mancanti"
            res["flags"] = [f"Ultimo bilancio disponibile troppo vecchio ({r.fy_last})"]
        elif pd.isna(r.get("price")):
            res["status"] = "dati mancanti"
            res["flags"] = ["Prezzo non disponibile"]
        if track in scorable_tracks:
            total, avail_pts, all_pts = 0.0, 0.0, 0.0
            for area, comps in cfg["components"][track].items():
                got, pts_av = 0.0, 0.0
                for metric, spec in comps.items():
                    p = comp_pct[f"{track}:{metric}"].get(i, np.nan)
                    all_pts += spec["points"]
                    res["components"][f"{area}.{metric}"] = {"area": area, "metric": metric, "points": spec["points"], "dir": spec["dir"],
                                                 "value": None if pd.isna(r.get(metric)) else r.get(metric),
                                                 "pct": None if pd.isna(p) else float(p)}
                    if not pd.isna(p):
                        got += p * spec["points"]
                        pts_av += spec["points"]
                avail_pts += pts_av
                tot_pts = sum(s["points"] for s in comps.values())
                if pts_av > 0:
                    area_score = weights[area] * got / pts_av
                else:
                    area_score = weights[area] * 0.5   # nessun dato: punteggio neutro
                res["areas"][area] = round(area_score, 2)
                total += area_score
            res["score"] = round(total, 1)
            res["coverage"] = avail_pts / all_pts if all_pts else None
            if res["status"] == "classificato":
                red = _red_flags(track, r.to_dict(), details[t]["rec"].get("info", {}), cfg)
                if red:
                    res["status"] = "escluso"
                    res["flags"] = red
        dq = data_quality(details[t]["rec"], cfg)
        res["data_quality"] = dq
        if (dq["status"] == "discordante" and cfg["data_check"]["exclude_discordant"]
                and res["status"] == "classificato"):
            res["status"] = "dati da verificare"
            res["flags"] = ["Yahoo e fonte ufficiale (" + str(dq["source"]) + ") non concordano: "
                            + "; ".join(dq["discordances"])]
        results.append(res)

    df["status"] = [x["status"] for x in results]
    df["score"] = [x.get("score") for x in results]
    order = df[df.status == "classificato"].sort_values("score", ascending=False).index
    df["rank"] = None
    df.loc[order, "rank"] = range(1, len(order) + 1)
    df["coverage"] = [x.get("coverage") for x in results]

    prev = _previous_snapshot()
    vts, exits, buckets = [], [], []
    for (i, r), res in zip(df.iterrows(), results):
        rd = r.to_dict()
        is_vt, why = (value_trap(rd, res["areas"], cfg, universe_med_12m)
                      if res["status"] == "classificato" else (False, None))
        res["value_trap"] = why
        med = medians.get(r.peer_group, {}) if r.peer_group else {}
        res["exit"] = exit_signals(rd, res["status"], res["flags"], med, prev.get(r.ticker), why, cfg)
        res["bucket"] = bucket(rd, cfg)
        vts.append(is_vt); exits.append(res["exit"]); buckets.append(res["bucket"])
    df["value_trap"] = vts
    df["bucket"] = buckets
    pf = build_portfolio(df, cfg)
    df["pf_weight"] = df["ticker"].map(dict(zip(pf["ticker"], pf["pf_weight"])))
    res_by_t = {r.ticker: res for (_, r), res in zip(df.iterrows(), results)}
    _export_portfolio(pf, df, res_by_t, cfg)

    _export(df, results, details, medians, cfg)

    from .tracking import save_snapshot, update_performance
    try:
        save_snapshot(df)
        update_performance()
    except Exception as e:  # lo storico non deve mai bloccare la classifica
        log.warning("Storico del modello non aggiornato: %s", e)


# ------------------------------------------------------------------ esportazione

def _previous_snapshot() -> dict:
    """Punteggi dell'ultima fotografia mensile precedente al mese corrente."""
    from datetime import date
    from .tracking import SNAP
    files = sorted(SNAP.glob("*.csv")) if SNAP.exists() else []
    files = [f for f in files if f.stem != f"{date.today():%Y-%m}"] or files[:-1]
    if not files:
        return {}
    snap = pd.read_csv(files[-1])
    return {r.ticker: {"score": r.score, "rank": r["rank"], "date": r.date} for _, r in snap.iterrows()}


BUCKET_LABEL = {"conviction": "Conviction", "protective": "Protective", "cyclical": "Cyclical"}


def _export_portfolio(pf: pd.DataFrame, df: pd.DataFrame, res_by_t: dict, cfg: dict) -> None:
    rows = [{"t": r.ticker, "n": r["name"], "rank": _f(r["rank"]), "score": _f(r["score"]),
             "bucket": BUCKET_LABEL[r["bucket"]], "weight": _f(r["pf_weight"]), "sector": r.sector,
             "country": r.country if isinstance(r.country, str) else r.region,
             "exit": res_by_t[r.ticker]["exit"]} for _, r in pf.iterrows()]
    mine = []
    for t in cfg.get("my_portfolio") or []:
        sub = df[df["ticker"] == t]
        if sub.empty:
            mine.append({"t": t, "n": t, "status": "non nell'universo",
                         "exit": ["Aggiungilo anche a extra_tickers in config.yaml per analizzarlo"]})
            continue
        r = sub.iloc[0]
        mine.append({"t": t, "n": r["name"], "rank": _f(r["rank"]), "score": _f(r["score"]),
                     "status": r["status"], "bucket": BUCKET_LABEL[r["bucket"]], "exit": res_by_t[t]["exit"]})
    p = cfg["portfolio"]
    write_json(SITE_DATA / "portfolio.json", {
        "rules": {"buckets": p["buckets"], "max_per_sector": p["max_per_sector"],
                  "max_country_share": p["max_country_share"]},
        "model": rows, "mine": mine}, compact=True)
    log.info("Portafoglio modello: %d titoli (%s)", len(rows), pf["bucket"].value_counts().to_dict())

def _rsi_state(v, lab):
    if v is None or pd.isna(v):
        return None
    return "Ipercomprato" if v > lab["rsi_overbought"] else "Ipervenduto" if v < lab["rsi_oversold"] else "Neutrale"


def _f(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else v


def _export(df: pd.DataFrame, results: list, details: dict, medians: dict, cfg: dict) -> None:
    lab = cfg["labels"]
    stocks_dir = SITE_DATA / "stocks"
    if stocks_dir.exists():
        shutil.rmtree(stocks_dir)
    stocks_dir.mkdir(parents=True)
    ranking = []
    for (i, r), res in zip(df.iterrows(), results):
        med = medians.get(r.peer_group, {}) if r.peer_group else {}
        fin = r.track in ("banca", "assicurazione")
        key1 = ("roe_avg", "ROE") if fin else ("ffo_margin", "Margine FFO") if r.track == "reit" else ("roic_avg", "ROIC")
        key2 = ("ptbv", "P/TBV") if fin else ("p_ffo", "P/FFO") if r.track == "reit" else ("ev_ebitda", "EV/EBITDA")
        ranking.append({
            "t": r.ticker, "n": r["name"], "rank": _f(r["rank"]), "score": res.get("score"),
            "status": res["status"], "flags": res["flags"], "region": r.region, "country": r.country,
            "sector": r.sector, "industry": r.industry, "track": r.track, "ciclico": bool(r.ciclico),
            "areas": res["areas"], "coverage": res.get("coverage"),
            "k1": {"label": key1[1], "v": _f(r.get(key1[0])), "med": med.get(key1[0])},
            "k2": {"label": key2[1], "v": _f(r.get(key2[0])), "med": med.get(key2[0])},
            "rsi": _f(r.get("rsi14")), "rsi_state": _rsi_state(_f(r.get("rsi14")), lab),
            "mcap": _f(r.get("market_cap_usd")), "price": _f(r.get("price")),
            "ccy": r.get("trading_currency"),
            "dq": res.get("data_quality", {}).get("status"), "vt": bool(res.get("value_trap")),
            "bucket": BUCKET_LABEL.get(res.get("bucket"), None), "pf": _f(r.get("pf_weight")),
            "exit": len(res.get("exit") or []),
        })
        rec, m = details[r.ticker]["rec"], details[r.ticker]["metrics"]
        detail = {
            "ticker": r.ticker, "name": r["name"], "rank": _f(r["rank"]), "status": res["status"],
            "flags": res["flags"], "score": res.get("score"), "areas": res["areas"],
            "components": res["components"], "coverage": res.get("coverage"),
            "track": r.track, "ciclico": bool(r.ciclico), "region": r.region, "index": r["index"],
            "peer_group": r.peer_group, "peer_n": med.get("n"), "peer_medians": med,
            "peer_revenue_cagr": _f(r.get("peer_revenue_cagr")),
            "peer_growth_consistency": _f(r.get("peer_growth_consistency")),
            "peer_growth_by_year": r.get("peer_growth_by_year") if isinstance(r.get("peer_growth_by_year"), dict) else None,
            "share_gain": _f(r.get("share_gain")),
            "roic_above_peer_share": _f(r.get("roic_above_peer_share")),
            "roe_above_peer_share": _f(r.get("roe_above_peer_share")),
            "info": {k: v for k, v in rec.get("info", {}).items()},
            "governance": rec.get("governance", {}), "sources": rec.get("sources", {}),
            "fetched_at": rec.get("fetched_at"), "metrics": m,
            "data_quality": res.get("data_quality"), "value_trap": res.get("value_trap"),
            "exit": res.get("exit"), "bucket": BUCKET_LABEL.get(res.get("bucket")),
            "pf_weight": _f(r.get("pf_weight")),
            "sector_trend": {"peer_ret_12m": _f(r.get("peer_price_12m")), "own_ret_12m": _f(r.get("ret_12m"))},
        }
        write_json(stocks_dir / f"{safe_name(r.ticker)}.json", detail, compact=True)

    # riepilogo leggibile salvato nel repository (prime 100 posizioni)
    top = df[df.status == "classificato"].sort_values("rank")[["rank", "ticker", "name", "region", "track",
                                                               "industry", "score"]].head(100)
    top.to_csv(DATA / "classifica_top100.csv", index=False)
    counts = df["status"].value_counts().to_dict()
    um = df.loc[df["track"].isin(["usuale", "banca", "assicurazione", "reit"]), "ret_12m"].median()
    meta = {"universe_ret_12m": None if pd.isna(um) else float(um),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "weights": cfg["area_weights"], "labels": lab, "counts": counts, "universe": len(df)}
    write_json(SITE_DATA / "ranking.json", {"meta": meta, "rows": ranking}, compact=True)
    log.info("Classifica esportata: %s", counts)
