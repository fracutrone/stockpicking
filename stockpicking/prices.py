"""Download dei prezzi (Yahoo Finance) e dei cambi.

Output:
  data/prices_daily.parquet   ultimi ~14 mesi, chiusura e volume (per tecnica e liquidità)
  data/prices_weekly.parquet  ultimi ~7 anni, chiusura settimanale (per multipli storici)
  data/fx_weekly.parquet      cambi settimanali verso USD
"""
from __future__ import annotations

import time

import pandas as pd
import yfinance as yf

from .common import DATA, log

FX_CCY = ["EUR", "GBP", "CHF", "SEK", "DKK", "NOK", "PLN", "JPY", "CNY", "HKD", "CAD",
          "AUD", "ILS", "ZAR", "BRL", "INR", "KRW", "TWD", "MXN", "SGD", "CZK", "HUF"]


def _download(tickers: list[str], period: str, interval: str, chunk: int = 100) -> pd.DataFrame:
    frames = []
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        for attempt in range(3):
            try:
                df = yf.download(part, period=period, interval=interval, group_by="ticker",
                                 auto_adjust=False, threads=True, progress=False)
                break
            except Exception as e:
                log.warning("Download prezzi fallito (tentativo %d): %s", attempt + 1, e)
                time.sleep(10 * (attempt + 1))
        else:
            continue
        if df is None or df.empty:
            continue
        if not isinstance(df.columns, pd.MultiIndex):  # un solo ticker
            df.columns = pd.MultiIndex.from_product([[part[0]], df.columns])
        long = df.stack(level=0, future_stack=True).reset_index()
        long.columns = [str(c) for c in long.columns]
        long = long.rename(columns={long.columns[0]: "date", long.columns[1]: "ticker"})
        keep = [c for c in ["date", "ticker", "Close", "Adj Close", "Volume"] if c in long.columns]
        frames.append(long[keep].dropna(subset=["Close"]))
        log.info("Prezzi %s: %d/%d", interval, min(i + chunk, len(tickers)), len(tickers))
        time.sleep(2)
    if not frames:
        return pd.DataFrame(columns=["date", "ticker", "Close", "Volume"])
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None)
    return out


BENCHMARKS = ["URTH"]   # iShares MSCI World (USD), riferimento per lo storico del modello


def update_prices(tickers: list[str]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tickers = list(dict.fromkeys(list(tickers) + BENCHMARKS))
    daily = _download(tickers, "14mo", "1d")
    if len(daily):
        daily.to_parquet(DATA / "prices_daily.parquet", index=False)
    weekly = _download(tickers, "7y", "1wk")
    if len(weekly):
        cols = [c for c in ["date", "ticker", "Close", "Adj Close"] if c in weekly.columns]
        weekly[cols].to_parquet(DATA / "prices_weekly.parquet", index=False)

    fx = _download([f"{c}USD=X" for c in FX_CCY], "7y", "1wk", chunk=50)
    if len(fx):
        fx["ccy"] = fx["ticker"].str[:3]
        fx[["date", "ccy", "Close"]].rename(columns={"Close": "usd_per_unit"}).to_parquet(
            DATA / "fx_weekly.parquet", index=False)
    log.info("Prezzi aggiornati: %d titoli con dati giornalieri", daily["ticker"].nunique() if len(daily) else 0)
