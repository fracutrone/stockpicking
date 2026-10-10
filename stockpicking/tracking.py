"""Storico del modello: ogni mese salva la classifica e ne misura il rendimento nel tempo.

- data/track/snapshots/AAAA-MM.csv  classifica del mese (tutti i classificati, con flag top 30)
- data/track/performance.csv       rendimento di ogni fotografia fino a oggi
- docs/data/track.json              stessi dati per la dashboard

Rendimenti totali (dividendi inclusi, prezzi rettificati), in dollari, pesi uguali.
Confronti: top 30 vs tutti i titoli classificati (stesso universo) vs MSCI World (URTH).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .common import DATA, SITE_DATA, log, write_json
from .metrics import FX

TRACK = DATA / "track"
SNAP = TRACK / "snapshots"
TOP_N = 30
BENCH = "URTH"


def _series_adj(weekly: pd.DataFrame) -> dict[str, pd.Series]:
    col = "Adj Close" if "Adj Close" in weekly.columns else "Close"
    return {t: g.set_index("date")[col].dropna().sort_index() for t, g in weekly.groupby("ticker")}


def _price_at(s: pd.Series | None, when) -> float | None:
    if s is None or s.empty:
        return None
    s2 = s[s.index <= pd.Timestamp(when)]
    return float(s2.iloc[-1]) if len(s2) else None


def save_snapshot(df: pd.DataFrame) -> None:
    """Fotografa la classifica una volta al mese (al primo calcolo del mese)."""
    today = date.today()
    path = SNAP / f"{today:%Y-%m}.csv"
    if path.exists():
        return
    ranked = df[df["status"] == "classificato"].sort_values("rank")
    if ranked.empty:
        return
    cols = ["rank", "ticker", "name", "region", "track", "score", "trading_currency"]
    if "pf_weight" in ranked.columns:
        cols.append("pf_weight")
    snap = ranked[cols].copy()
    snap["top"] = snap["rank"] <= TOP_N
    snap["date"] = today.isoformat()
    SNAP.mkdir(parents=True, exist_ok=True)
    snap.to_csv(path, index=False)
    log.info("Storico: salvata la classifica di %s (%d titoli, top %d)", f"{today:%Y-%m}", len(snap), TOP_N)


def update_performance() -> None:
    files = sorted(SNAP.glob("*.csv")) if SNAP.exists() else []
    wpath = DATA / "prices_weekly.parquet"
    if not files or not wpath.exists():
        return
    weekly = pd.read_parquet(wpath)
    fxw = pd.read_parquet(DATA / "fx_weekly.parquet") if (DATA / "fx_weekly.parquet").exists() else None
    fx = FX(fxw)
    adj = _series_adj(weekly)
    end = weekly["date"].max()

    def ret_usd(ticker, ccy, start):
        s = adj.get(ticker)
        p0, p1 = _price_at(s, start), _price_at(s, end)
        if not p0 or not p1:
            return None
        r0, r1 = fx.usd_rate(ccy, start), fx.usd_rate(ccy, end)
        if r0 is None or r1 is None:
            return None
        return (p1 * r1) / (p0 * r0) - 1

    rows = []
    for f in files:
        snap = pd.read_csv(f)
        start = snap["date"].iloc[0]
        snap["ret"] = [ret_usd(t, c, start) for t, c in zip(snap["ticker"], snap["trading_currency"])]
        top = snap[snap["top"]]["ret"].dropna()
        allr = snap["ret"].dropna()
        pf = None
        if "pf_weight" in snap.columns:
            w = snap.dropna(subset=["pf_weight", "ret"])
            if len(w) and w["pf_weight"].sum() > 0:
                pf = float((w["pf_weight"] * w["ret"]).sum() / w["pf_weight"].sum())
        b = adj.get(BENCH)
        b0, b1 = _price_at(b, start), _price_at(b, end)
        bench = b1 / b0 - 1 if b0 and b1 else None
        rows.append({
            "snapshot": f.stem, "start": start, "end": end.date().isoformat(),
            "days": (end - pd.Timestamp(start)).days,
            "top30": top.mean() if len(top) else None, "top30_n": int(len(top)),
            "portafoglio_modello": pf,
            "universo": allr.mean() if len(allr) else None, "universo_n": int(len(allr)),
            "msci_world": bench,
            "extra_vs_universo": (top.mean() - allr.mean()) if len(top) and len(allr) else None,
            "extra_vs_msci": (top.mean() - bench) if len(top) and bench is not None else None,
            "top30_tickers": ", ".join(snap[snap["top"]]["ticker"].astype(str)),
        })
    perf = pd.DataFrame(rows)
    TRACK.mkdir(parents=True, exist_ok=True)
    perf.to_csv(TRACK / "performance.csv", index=False)
    write_json(SITE_DATA / "track.json", {"top_n": TOP_N, "benchmark": "MSCI World (URTH)",
                                          "rows": perf.to_dict("records")}, compact=True)
    log.info("Storico: aggiornato il rendimento di %d fotografie", len(perf))
