"""Bilanci annuali ufficiali delle società USA dalla SEC (API XBRL companyfacts).

Restituisce, per ogni voce di bilancio, una serie {data_fine_esercizio: valore}
presa dai 10-K (in caso di riesposizioni vale l'ultimo deposito).
"""
from __future__ import annotations

import os
import time
from datetime import date

import requests

from .common import DATA, log, read_json, write_json

SEC_UA = os.environ.get("SEC_USER_AGENT", "stockpicking research github.com/fracutrone/stockpicking")
HEAD = {"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}

# voci di flusso (durata annuale): la prima etichetta disponibile vince
FLOW_TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "RevenuesNetOfInterestExpense"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet", "Depreciation"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                         "InterestAndDebtExpense"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "nii": ["InterestIncomeExpenseNet"],
    "noninterest_expense": ["NoninterestExpense"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}

# voci patrimoniali (istantanee a fine esercizio)
INSTANT_TAGS = {
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "total_liabilities": ["Liabilities"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"],
    "st_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "inventory": ["InventoryNet"],
    "ppe_net": ["PropertyPlantAndEquipmentNet"],
    "goodwill": ["Goodwill"],
    "intangibles": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "debt_lt_total": ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"],
    "debt_lt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligationsNoncurrent"],
    "debt_lt_current": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "debt_st": ["ShortTermBorrowings", "CommercialPaper"],
}

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A"}


_CIK_FAILED = [False]


def _cik_map() -> dict[str, int]:
    if _CIK_FAILED[0]:
        return {}
    path = DATA / "sec_tickers.json"
    cached = read_json(path)
    if cached and cached.get("_date") == date.today().isoformat():
        return cached["map"]
    r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=HEAD, timeout=30)
    if r.status_code == 403:
        _CIK_FAILED[0] = True
        log.warning("SEC rifiuta la richiesta (403): imposta il secret SEC_USER_AGENT con nome ed email. "
                    "Per ora i bilanci USA vengono solo da Yahoo.")
        return {}
    r.raise_for_status()
    m = {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in r.json().values()}
    write_json(path, {"_date": date.today().isoformat(), "map": m}, compact=True)
    return m


_LAST_CALL = [0.0]


def _get_facts(cik: int) -> dict | None:
    wait = 0.15 - (time.time() - _LAST_CALL[0])  # limite SEC: 10 richieste/secondo
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[0] = time.time()
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEAD, timeout=60)
            if r.status_code == 404:
                return None
            if r.status_code == 403:
                log.warning("SEC rifiuta la richiesta (403): imposta il secret SEC_USER_AGENT con nome ed email")
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.debug("SEC %s tentativo %d: %s", cik, attempt + 1, e)
            time.sleep(2 * (attempt + 1))
    return None


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _series(facts: dict, tags: list[str], instant: bool, unit: str = "USD") -> dict[str, float]:
    """Unisce le etichette in ordine di priorità: per ogni fine esercizio vale la prima etichetta che lo riporta.
    (Le società cambiano etichetta nel tempo, es. SalesRevenueNet -> RevenueFromContractWithCustomer...)"""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    merged: dict[str, float] = {}
    for tag in tags:
        entries = gaap.get(tag, {}).get("units", {}).get(unit)
        if not entries:
            continue
        found: dict[str, tuple[str, float]] = {}
        for e in entries:
            if e.get("form") not in ANNUAL_FORMS:
                continue
            if instant:
                if "start" in e:
                    continue
            else:
                if "start" not in e or not 340 <= _days(e["start"], e["end"]) <= 380:
                    continue
            end, filed = e["end"], e.get("filed", "")
            if end not in found or filed > found[end][0]:
                found[end] = (filed, float(e["val"]))
        for end, (_, val) in found.items():
            if end not in merged:
                merged[end] = val
    return merged


def fetch_sec_financials(ticker: str) -> dict | None:
    """Ritorna {voce: {fine_esercizio: valore}} oppure None se il titolo non è alla SEC."""
    try:
        cik = _cik_map().get(ticker.upper())
    except Exception as e:
        log.warning("Elenco CIK SEC non disponibile: %s", e)
        return None
    if not cik:
        return None
    facts = _get_facts(cik)
    if not facts:
        return None
    out: dict[str, dict[str, float]] = {}
    for k, tags in FLOW_TAGS.items():
        out[k] = _series(facts, tags, instant=False, unit="shares" if k == "shares_diluted" else "USD")
    for k, tags in INSTANT_TAGS.items():
        out[k] = _series(facts, tags, instant=True)

    # debito totale
    debt: dict[str, float] = {}
    ends = set(out["debt_lt_total"]) | set(out["debt_lt_noncurrent"]) | set(out["debt_st"])
    for end in ends:
        lt = out["debt_lt_total"].get(end)
        if lt is None:
            nc, cur = out["debt_lt_noncurrent"].get(end), out["debt_lt_current"].get(end)
            lt = (nc or 0) + (cur or 0) if (nc is not None or cur is not None) else None
        st = out["debt_st"].get(end)
        if lt is not None or st is not None:
            debt[end] = (lt or 0) + (st or 0)
    out["total_debt"] = debt
    for k in ["debt_lt_total", "debt_lt_noncurrent", "debt_lt_current", "debt_st"]:
        out.pop(k)
    return out


def latest_annual_filing(ticker: str):
    """Data dell'ultimo bilancio annuale (10-K/20-F) depositato alla SEC, o None."""
    try:
        cik = _cik_map().get(ticker.upper())
    except Exception:
        return None
    if not cik:
        return None
    wait = 0.15 - (time.time() - _LAST_CALL[0])
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[0] = time.time()
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=HEAD, timeout=30)
        if r.status_code != 200:
            return None
        rec = r.json().get("filings", {}).get("recent", {})
        dates = [d for f, d in zip(rec.get("form", []), rec.get("filingDate", []))
                 if f in ANNUAL_FORMS or f in ("20-F", "40-F")]
        return date.fromisoformat(max(dates)) if dates else None
    except Exception as e:
        log.debug("SEC submissions %s: %s", ticker, e)
        return None
