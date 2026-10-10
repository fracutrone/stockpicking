"""Diagnostica: verifica quali servizi di Yahoo e SEC rispondono dal server di GitHub."""
from __future__ import annotations

import traceback

import yfinance as yf

from .common import log


def _try(name, fn):
    try:
        v = fn()
        size = len(v) if hasattr(v, "__len__") else "-"
        shape = getattr(v, "shape", None)
        log.info("DIAG %-28s OK  tipo=%s len=%s shape=%s", name, type(v).__name__, size, shape)
        if isinstance(v, dict):
            log.info("DIAG    chiavi: %s", list(v.keys())[:15])
        return v
    except Exception as e:
        log.info("DIAG %-28s ERR %s: %s", name, type(e).__name__, str(e)[:200])
        log.debug(traceback.format_exc())


def run() -> None:
    log.info("DIAG yfinance %s", yf.__version__)
    for tk in ["AAPL", "ENI.MI"]:
        t = yf.Ticker(tk)
        _try(f"{tk} info", lambda: t.info)
        _try(f"{tk} fast_info", lambda: dict(t.fast_info))
        _try(f"{tk} income_stmt", lambda: t.income_stmt)
        _try(f"{tk} balance_sheet", lambda: t.balance_sheet)
        _try(f"{tk} cashflow", lambda: t.cashflow)
        _try(f"{tk} institutional_holders", lambda: t.institutional_holders)
        _try(f"{tk} major_holders", lambda: t.major_holders)
        _try(f"{tk} insider_purchases", lambda: t.insider_purchases)
        _try(f"{tk} get_shares_full", lambda: t.get_shares_full(start="2025-01-01"))
        _try(f"{tk} history", lambda: t.history(period="5d"))
    try:
        from .sec import fetch_sec_financials
        s = fetch_sec_financials("AAPL")
        log.info("DIAG SEC AAPL: %s", {k: len(v) for k, v in (s or {}).items()})
    except Exception as e:
        log.info("DIAG SEC ERR %s", e)
