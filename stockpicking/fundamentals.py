"""Bilanci annuali, anagrafica e governance per ogni titolo.

Fonti: Yahoo Finance per tutti; per i titoli USA ogni voce di bilancio usa la serie SEC
se è lunga almeno quanto quella di Yahoo (stessa fonte per tutti gli anni della voce).
Output: data/fundamentals/<ticker>.json
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from .common import FUND_DIR, load_config, log, read_json, safe_name, write_json
from .sec import fetch_sec_financials, latest_annual_filing

# voce -> (prospetto yahoo, etichette in ordine di preferenza)
YAHOO_MAP = {
    "revenue": ("is", ["Total Revenue", "Operating Revenue"]),
    "cogs": ("is", ["Cost Of Revenue", "Reconciled Cost Of Revenue"]),
    "gross_profit": ("is", ["Gross Profit"]),
    "operating_income": ("is", ["Operating Income"]),
    "ebitda_reported": ("is", ["EBITDA", "Normalized EBITDA"]),
    "da": ("cf", ["Depreciation And Amortization", "Depreciation Amortization Depletion",
                  "Reconciled Depreciation"]),
    "interest_expense": ("is", ["Interest Expense", "Interest Expense Non Operating"]),
    "pretax_income": ("is", ["Pretax Income"]),
    "tax": ("is", ["Tax Provision"]),
    "net_income": ("is", ["Net Income", "Net Income Common Stockholders",
                          "Net Income Including Noncontrolling Interests"]),
    "sga": ("is", ["Selling General And Administration"]),
    "nii": ("is", ["Net Interest Income"]),
    "noninterest_expense": ("is", ["Non Interest Expense", "Operating Expense"]),
    "shares_diluted": ("is", ["Diluted Average Shares", "Basic Average Shares"]),
    "cfo": ("cf", ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]),
    "capex": ("cf", ["Capital Expenditure"]),
    "total_assets": ("bs", ["Total Assets"]),
    "current_assets": ("bs", ["Current Assets"]),
    "current_liabilities": ("bs", ["Current Liabilities"]),
    "total_liabilities": ("bs", ["Total Liabilities Net Minority Interest"]),
    "cash": ("bs", ["Cash And Cash Equivalents", "Cash Financial"]),
    "st_investments": ("bs", ["Other Short Term Investments"]),
    "equity": ("bs", ["Stockholders Equity", "Common Stock Equity"]),
    "receivables": ("bs", ["Accounts Receivable", "Receivables"]),
    "inventory": ("bs", ["Inventory"]),
    "ppe_net": ("bs", ["Net PPE"]),
    "goodwill": ("bs", ["Goodwill"]),
    "intangibles": ("bs", ["Other Intangible Assets"]),
    "goodwill_and_intangibles": ("bs", ["Goodwill And Other Intangible Assets"]),
    "retained_earnings": ("bs", ["Retained Earnings"]),
    "total_debt": ("bs", ["Total Debt"]),
    "shares_out": ("bs", ["Ordinary Shares Number", "Share Issued"]),
}

INFO_KEYS = ["longName", "shortName", "sector", "industry", "country", "currency", "financialCurrency",
             "marketCap", "sharesOutstanding", "floatShares", "heldPercentInsiders",
             "heldPercentInstitutions", "shortPercentOfFloat", "averageVolume", "quoteType",
             "exchange", "fullTimeEmployees", "website", "longBusinessSummary"]


def _yahoo_series(df: pd.DataFrame | None, labels: list[str]) -> dict[str, float]:
    if df is None or df.empty:
        return {}
    for lab in labels:
        if lab in df.index:
            s = df.loc[lab].dropna()
            if len(s):
                return {pd.Timestamp(k).date().isoformat(): float(v) for k, v in s.items()}
    return {}


def _match_end(end: str, ends: list[str], tol: int = 25) -> str | None:
    d = datetime.fromisoformat(end)
    for e in ends:
        if abs((datetime.fromisoformat(e) - d).days) <= tol:
            return e
    return None


class FetchError(Exception):
    pass


def _call(fn, default=None, tries: int = 3, required: bool = False):
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            msg = str(e)
            if "Rate" in msg or "Too Many" in msg or "429" in msg:
                wait = 30 * (attempt + 1)
                log.warning("Yahoo limita le richieste, attendo %ds", wait)
                time.sleep(wait)
            else:
                log.debug("chiamata fallita: %s", e)
                time.sleep(1)
    if required:
        raise FetchError(f"{type(last).__name__}: {last}")
    return default


def _governance(t: yf.Ticker, info: dict) -> dict:
    gov: dict = {}
    officers = info.get("companyOfficers") or []
    ceo = next((o for o in officers if "ceo" in (o.get("title") or "").lower()
                or "chief executive" in (o.get("title") or "").lower()), None)
    if ceo:
        gov["ceo"] = {"name": ceo.get("name"), "title": ceo.get("title"),
                      "age": ceo.get("age"), "year_born": ceo.get("yearBorn"),
                      "total_pay": ceo.get("totalPay")}
    holders = _call(lambda: t.institutional_holders)
    if isinstance(holders, pd.DataFrame) and len(holders):
        col_pct = "pctHeld" if "pctHeld" in holders.columns else None
        gov["top_institutions"] = [
            {"name": r.get("Holder"), "pct": float(r[col_pct]) if col_pct and pd.notna(r[col_pct]) else None}
            for _, r in holders.head(3).iterrows()]
    ip = _call(lambda: t.insider_purchases)
    if isinstance(ip, pd.DataFrame) and len(ip) and ip.shape[1] >= 2:
        first = ip.columns[0]
        shares_col = "Shares" if "Shares" in ip.columns else ip.columns[1]
        rows = {str(r[first]): r[shares_col] for _, r in ip.iterrows()}
        def num(k):
            v = rows.get(k)
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        gov["insider_6m"] = {"purchases": num("Purchases"), "sales": num("Sales"),
                             "net_shares": num("Net Shares Purchased (Sold)"),
                             "net_pct": num("% Net Shares Purchased (Sold)")}
    return gov


def fetch_one(ticker: str, region: str) -> dict | None:
    t = yf.Ticker(ticker)
    info = _call(lambda: t.info, required=True) or {}
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not info or not (info.get("longName") or info.get("shortName")):
        return {"ticker": ticker, "fetched_at": stamp, "skip": "nessun dato su Yahoo"}
    if info.get("quoteType") not in (None, "EQUITY"):
        return {"ticker": ticker, "fetched_at": stamp, "skip": f"non è un'azione ({info.get('quoteType')})"}
    stm = {
        "is": _call(lambda: t.income_stmt),
        "bs": _call(lambda: t.balance_sheet),
        "cf": _call(lambda: t.cashflow),
    }
    yahoo = {k: _yahoo_series(stm[s], labels) for k, (s, labels) in YAHOO_MAP.items()}
    if "capex" in yahoo:
        yahoo["capex"] = {k: abs(v) for k, v in yahoo["capex"].items()}

    series = dict(yahoo)
    sources = {k: "yahoo" for k in yahoo if yahoo[k]}
    currency = info.get("financialCurrency") or info.get("currency")

    if region == "USA":
        sec = _call(lambda: fetch_sec_financials(ticker))
        if sec:
            for k, s in sec.items():
                y = series.get(k, {})
                if not s:
                    continue
                # la serie SEC vale solo se arriva aggiornata almeno quanto quella di Yahoo
                fresh = not y or datetime.fromisoformat(max(s)) >= datetime.fromisoformat(max(y)) - timedelta(days=25)
                if fresh and len(s) >= len(y):
                    series[k] = s
                    sources[k] = "sec"
            if any(v == "sec" for v in sources.values()):
                currency = "USD"

    # elenco degli esercizi: dalle date di fine di ricavi / utile / attivo
    anchor = series.get("revenue") or series.get("net_income") or series.get("total_assets") or {}
    ends = sorted(anchor.keys(), reverse=True)[:7]
    years = []
    for end in ends:
        row = {"fy_end": end}
        for k, s in series.items():
            if not s:
                continue
            m = end if end in s else _match_end(end, list(s.keys()))
            if m is not None:
                row[k] = s[m]
        years.append(row)

    return {
        "ticker": ticker,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region": region,
        "statement_currency": currency,
        "info": {k: info.get(k) for k in INFO_KEYS},
        "governance": _governance(t, info),
        "sources": sources,
        "years": sorted(years, key=lambda r: r["fy_end"]),
    }


def _needs_refresh(old: dict | None, region: str, now: datetime, cfg: dict) -> tuple[bool, str]:
    """Riscarica solo se c'è un bilancio annuale nuovo (o probabile), al massimo una volta al mese."""
    if not old:
        return True, "mai scaricato"
    fetched = datetime.fromisoformat(old["fetched_at"])
    if now - fetched < timedelta(days=cfg["fundamentals_min_days_between_checks"]):
        return False, "controllato di recente"
    if old.get("skip"):
        return True, "nuovo tentativo"
    years = old.get("years") or []
    if not years:
        return True, "nessun esercizio"
    fy_last = datetime.fromisoformat(years[-1]["fy_end"]).replace(tzinfo=timezone.utc)
    if region == "USA":
        filed = latest_annual_filing(old["ticker"])
        if filed is not None:
            return (filed > fetched.date()), ("nuovo 10-K depositato" if filed > fetched.date() else "nessun nuovo 10-K")
    # Europa (o SEC non disponibile): il nuovo bilancio esce di norma entro pochi mesi dalla chiusura
    due = fy_last + timedelta(days=365 + cfg["annual_report_lag_days"])
    if now >= due:
        return True, "nuovo bilancio annuale atteso"
    return False, "nessun bilancio nuovo atteso"


def update_fundamentals(universe: pd.DataFrame, limit: int | None = None, force: bool = False) -> int:
    cfg = load_config()["general"]
    limit = limit or cfg["fundamentals_batch_per_run"]
    now = datetime.now(timezone.utc)

    queue, reasons = [], {}
    for _, r in universe.iterrows():
        old = read_json(FUND_DIR / f"{safe_name(r.ticker)}.json")
        need, why = (True, "forzato") if force else _needs_refresh(old, r.region, now, cfg)
        reasons[why] = reasons.get(why, 0) + 1
        if need:
            ts = datetime.fromisoformat(old["fetched_at"]) if old else datetime(2000, 1, 1, tzinfo=timezone.utc)
            queue.append((ts, r.ticker, r.region))
    queue.sort()
    queue = queue[:limit]
    log.info("Controllo bilanci: %s", reasons)
    log.info("Bilanci da aggiornare: %d (limite %d)", len(queue), limit)

    done, consecutive_err = 0, 0
    for i, (_, ticker, region) in enumerate(queue, 1):
        try:
            data = fetch_one(ticker, region)
            consecutive_err = 0
        except Exception as e:
            log.warning("%s: errore %s", ticker, e)
            data = None
            consecutive_err += 1
            if consecutive_err >= 15:
                log.error("Troppi errori consecutivi da Yahoo: interrompo i bilanci (ultimo: %s)", e)
                break
        if data:
            write_json(FUND_DIR / f"{safe_name(ticker)}.json", data)
            done += 1
        if i % 25 == 0:
            log.info("Bilanci: %d/%d", i, len(queue))
        time.sleep(0.5)
    log.info("Bilanci aggiornati: %d", done)
    return done
