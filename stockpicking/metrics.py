"""Calcolo degli indicatori di ogni titolo a partire da bilanci, prezzi e cambi."""
from __future__ import annotations

import math
from statistics import mean, pstdev

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ helper numerici

def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def div(a, b):
    a, b = _num(a), _num(b)
    if a is None or b is None or b == 0:
        return None
    return a / b


def cagr(first, last, years):
    first, last = _num(first), _num(last)
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def avg(vals):
    v = [x for x in vals if x is not None]
    return mean(v) if v else None


def std(vals):
    v = [x for x in vals if x is not None]
    return pstdev(v) if len(v) >= 2 else None


def cv_stability(vals):
    """Stabilità = -(deviazione standard / media). Più alto = più stabile."""
    v = [x for x in vals if x is not None]
    if len(v) < 3:
        return None
    m = mean(v)
    if m <= 0:
        return None
    return -(pstdev(v) / m)


def share(vals, cond):
    v = [x for x in vals if x is not None]
    return sum(1 for x in v if cond(x)) / len(v) if v else None


# ------------------------------------------------------------------ cambi

class FX:
    """Converte importi tra valute usando i cambi settimanali verso USD."""

    def __init__(self, fx_weekly: pd.DataFrame | None):
        self.tab: dict[str, pd.Series] = {}
        if fx_weekly is not None and len(fx_weekly):
            for ccy, g in fx_weekly.groupby("ccy"):
                self.tab[ccy] = g.set_index("date")["usd_per_unit"].sort_index()

    @staticmethod
    def _norm(ccy: str | None) -> tuple[str | None, float]:
        if not ccy:
            return None, 1.0
        if ccy in ("GBp", "GBX"):
            return "GBP", 0.01
        if ccy == "ILA":
            return "ILS", 0.01
        if ccy == "ZAc":
            return "ZAR", 0.01
        return ccy.upper(), 1.0

    def usd_rate(self, ccy: str | None, when=None) -> float | None:
        c, mult = self._norm(ccy)
        if c is None:
            return None
        if c == "USD":
            return mult
        s = self.tab.get(c)
        if s is None or s.empty:
            return None
        if when is None:
            return float(s.iloc[-1]) * mult
        s2 = s[s.index <= pd.Timestamp(when)]
        return float((s2 if len(s2) else s).iloc[-1 if len(s2) else 0]) * mult

    def convert(self, amount, from_ccy, to_ccy, when=None):
        amount = _num(amount)
        if amount is None:
            return None
        if self._norm(from_ccy) == self._norm(to_ccy):
            return amount
        a, b = self.usd_rate(from_ccy, when), self.usd_rate(to_ccy, when)
        if a is None or b is None or b == 0:
            return None
        return amount * a / b


# ------------------------------------------------------------------ tecnica

def technicals(close: pd.Series, volume: pd.Series | None) -> dict:
    out: dict = {}
    close = close.dropna()
    if len(close) < 30:
        return out
    price = float(close.iloc[-1])
    out["price"] = price
    out["price_date"] = close.index[-1].date().isoformat()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else np.inf
    out["rsi14"] = float(100 - 100 / (1 + rs))
    if len(close) >= 50:
        out["sma50"] = float(close.iloc[-50:].mean())
    if len(close) >= 200:
        out["sma200"] = float(close.iloc[-200:].mean())
        out["dist_sma200"] = price / out["sma200"] - 1
    if len(close) >= 252:
        out["ret_12m"] = price / float(close.iloc[-252]) - 1
    if len(close) >= 126:
        out["ret_6m"] = price / float(close.iloc[-126]) - 1
    last = close.iloc[-252:]
    out["high_52w"], out["low_52w"] = float(last.max()), float(last.min())
    out["dist_high_52w"] = price / out["high_52w"] - 1
    if volume is not None:
        v = volume.reindex(close.index).iloc[-63:]
        out["avg_volume_3m"] = float(v.mean()) if v.notna().any() else None
        out["avg_value_3m_local"] = float((v * close.iloc[-63:]).mean()) if v.notna().any() else None
    return out


# ------------------------------------------------------------------ indicatori da bilancio

def _ebitda(y: dict):
    oi, da = _num(y.get("operating_income")), _num(y.get("da"))
    if oi is not None and da is not None:
        return oi + abs(da)
    return _num(y.get("ebitda_reported"))


def _tax_rate(y: dict) -> float:
    rate = div(y.get("tax"), y.get("pretax_income"))
    return 0.25 if rate is None else min(max(rate, 0.0), 0.35)


def _ni_adj(y: dict):
    """Utile netto rettificato per le voci straordinarie (al netto delle tasse)."""
    ni = _num(y.get("net_income"))
    if ni is None:
        return None
    u = _num(y.get("unusual_items"))
    if u is not None:
        return ni - u * (1 - _tax_rate(y))
    return ni


def _gross_margin(y: dict):
    gp = _num(y.get("gross_profit"))
    rev = _num(y.get("revenue"))
    if gp is None and rev is not None and _num(y.get("cogs")) is not None:
        gp = rev - abs(y["cogs"])
    return div(gp, rev)


def _net_debt(y: dict):
    debt = _num(y.get("total_debt"))
    if debt is None:
        return None
    return debt - (_num(y.get("cash")) or 0) - (_num(y.get("st_investments")) or 0)


def _roic(y: dict):
    oi = _num(y.get("operating_income"))
    if oi is None:
        return None
    rate = div(y.get("tax"), y.get("pretax_income"))
    rate = 0.25 if rate is None else min(max(rate, 0.0), 0.35)
    ic = (_num(y.get("equity")) or 0) + (_num(y.get("total_debt")) or 0) - (_num(y.get("cash")) or 0)
    if ic <= 0:
        return None
    return oi * (1 - rate) / ic


def _tangible_equity(y: dict):
    eq = _num(y.get("equity"))
    if eq is None:
        return None
    gi = _num(y.get("goodwill_and_intangibles"))
    if gi is None:
        gi = (_num(y.get("goodwill")) or 0) + (_num(y.get("intangibles")) or 0)
    return eq - gi


def beneish(t: dict, p: dict):
    """M-Score di Beneish a 8 variabili (t = esercizio corrente, p = precedente)."""
    need = ["revenue", "receivables", "current_assets", "ppe_net", "total_assets", "net_income", "cfo"]
    if any(_num(t.get(k)) is None or _num(p.get(k)) is None for k in need):
        return None
    st, sp = t["revenue"], p["revenue"]
    if st <= 0 or sp <= 0:
        return None
    dsri = div(div(t["receivables"], st), div(p["receivables"], sp))
    gm_t, gm_p = _gross_margin(t), _gross_margin(p)
    gmi = div(gm_p, gm_t) if gm_t and gm_p and gm_t > 0 else 1.0
    aq_t = 1 - (t["current_assets"] + t["ppe_net"]) / t["total_assets"]
    aq_p = 1 - (p["current_assets"] + p["ppe_net"]) / p["total_assets"]
    aqi = div(aq_t, aq_p) if aq_p else 1.0
    sgi = st / sp
    dt, dp = _num(t.get("da")), _num(p.get("da"))
    if dt and dp:
        depi = div(abs(dp) / (abs(dp) + p["ppe_net"]), abs(dt) / (abs(dt) + t["ppe_net"])) or 1.0
    else:
        depi = 1.0
    sgai = div(div(t.get("sga"), st), div(p.get("sga"), sp)) or 1.0
    lev_t = div((_num(t.get("current_liabilities")) or 0) + (_num(t.get("total_debt")) or 0), t["total_assets"])
    lev_p = div((_num(p.get("current_liabilities")) or 0) + (_num(p.get("total_debt")) or 0), p["total_assets"])
    lvgi = div(lev_t, lev_p) or 1.0
    tata = (t["net_income"] - t["cfo"]) / t["total_assets"]
    if dsri is None:
        return None
    return (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * (aqi or 1.0) + 0.892 * sgi + 0.115 * depi
            - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)


def altman(t: dict, mcap_fin):
    ta, tl = _num(t.get("total_assets")), _num(t.get("total_liabilities"))
    if not ta or not tl or mcap_fin is None:
        return None
    ca, cl, re_ = _num(t.get("current_assets")), _num(t.get("current_liabilities")), _num(t.get("retained_earnings"))
    ebit, sales = _num(t.get("operating_income")), _num(t.get("revenue"))
    if None in (ca, cl, re_, ebit, sales):
        return None
    return 1.2 * (ca - cl) / ta + 1.4 * re_ / ta + 3.3 * ebit / ta + 0.6 * mcap_fin / tl + 1.0 * sales / ta


# ------------------------------------------------------------------ calcolo completo

def compute(rec: dict, tech: dict, weekly_close: pd.Series | None, fx: FX, cfg: dict) -> dict:
    info = rec.get("info", {})
    gen = cfg["general"]
    years = rec.get("years", [])[-(gen["history_years"] + 1):]   # 5 anni di variazioni = 6 esercizi max
    hist = years[-gen["history_years"]:]
    fin_ccy = rec.get("statement_currency") or info.get("financialCurrency") or info.get("currency")
    trade_ccy = info.get("currency")
    m: dict = {"n_years": len(hist), "fy_last": hist[-1]["fy_end"] if hist else None,
               "statement_currency": fin_ccy, "trading_currency": trade_ccy}
    if not hist:
        return m
    last = hist[-1]
    n = len(hist) - 1

    # --- capitalizzazione nella valuta di bilancio
    price = tech.get("price")
    shares = _num(info.get("sharesOutstanding")) or _num(last.get("shares_out")) or _num(last.get("shares_diluted"))
    mcap_trade = price * shares if price and shares else None
    mcap_fin = fx.convert(mcap_trade, trade_ccy, fin_ccy)
    m["market_cap_usd"] = fx.convert(mcap_trade, trade_ccy, "USD")
    m["price"] = price
    m["revenue_usd"] = fx.convert(last.get("revenue"), fin_ccy, "USD")
    adv = tech.get("avg_value_3m_local")
    m["avg_daily_value_usd"] = fx.convert(adv, trade_ccy, "USD")

    # --- serie annuali
    rev = [_num(y.get("revenue")) for y in hist]
    ni_rep = [_num(y.get("net_income")) for y in hist]
    ni = [_ni_adj(y) for y in hist]          # utile rettificato per le voci straordinarie
    ebitda = [_ebitda(y) for y in hist]
    m["unusual_items_last"] = _num(last.get("unusual_items"))
    m["net_income_reported"] = ni_rep[-1]
    m["net_income_adjusted"] = ni[-1]
    # EBITDA dell'ultimo esercizio: versione normalizzata se disponibile e plausibile
    ebitda_last = ebitda[-1]
    ne = _num(last.get("normalized_ebitda"))
    if ne and ebitda_last and ne > 0 and 0.5 <= ne / ebitda_last <= 2:
        ebitda_last = ne
    m["ebitda_reported"] = ebitda[-1]
    m["ebitda_adjusted"] = ebitda_last
    fcf = [(_num(y.get("cfo")) - (abs(_num(y.get("capex"))) if _num(y.get("capex")) is not None else 0))
           if _num(y.get("cfo")) is not None else None for y in hist]
    gm = [_gross_margin(y) for y in hist]
    roic = [_roic(y) for y in hist]
    roe = [div(_ni_adj(y), y.get("equity")) if (_num(y.get("equity")) or 0) > 0 else None for y in hist]
    ebitda_m = [div(e, r) for e, r in zip(ebitda, rev)]
    m["series"] = {"fy": [y["fy_end"][:4] for y in hist], "revenue": rev, "net_income": ni, "ebitda": ebitda,
                   "fcf": fcf, "gross_margin": gm, "roic": roic, "roe": roe}
    growth = {}
    for a, b in zip(hist[:-1], hist[1:]):
        g = div(_num(b.get("revenue")), _num(a.get("revenue")))
        if g is not None and _num(a.get("revenue")) and a["revenue"] > 0:
            growth[b["fy_end"][:4]] = g - 1
    m["revenue_growth_by_year"] = growth

    # --- nucleo
    m["revenue_cagr"] = cagr(rev[0], rev[-1], n)
    m["ebitda_cagr"] = cagr(ebitda[0], ebitda[-1], n)
    both_adj = _num(hist[0].get("unusual_items")) is not None and _num(last.get("unusual_items")) is not None
    m["net_income_cagr"] = cagr(ni[0], ni[-1], n) if both_adj else cagr(ni_rep[0], ni_rep[-1], n)
    k = min(3, len(hist))
    fcf3, rev3 = [x for x in fcf[-k:] if x is not None], [x for x in rev[-k:] if x is not None]
    m["fcf_margin"] = div(sum(fcf3), sum(rev3)) if fcf3 and rev3 and len(fcf3) == len(rev3) else None
    m["fcf_positive_share"] = share(fcf, lambda x: x > 0)
    m["net_margin"] = div(ni[-1], rev[-1])
    m["gross_margin"] = gm[-1]
    eq = _num(last.get("equity"))
    m["negative_equity"] = eq is not None and eq <= 0
    m["debt_to_equity"] = div(last.get("total_debt"), eq) if eq and eq > 0 else None
    nd = _net_debt(last)
    m["net_debt"] = nd
    m["net_debt_to_ebitda"] = div(nd, ebitda_last) if ebitda_last and ebitda_last > 0 else None
    ie = _num(last.get("interest_expense"))
    oi = _num(last.get("operating_income"))
    if oi is not None and ie is not None and abs(ie) > 0:
        m["interest_coverage"] = min(oi / abs(ie), 100.0)
    elif oi is not None and oi > 0 and (ie is None or ie == 0):
        m["interest_coverage"] = 100.0 if (_num(last.get("total_debt")) or 0) == 0 else None
    m["roic"] = roic[-1]
    m["ebitda_margin"] = ebitda_m[-1]

    # --- moat
    m["roic_avg"] = avg(roic)
    m["roic_stability"] = cv_stability(roic)
    m["roic_by_year"] = dict(zip([y["fy_end"][:4] for y in hist], roic))
    m["gross_margin_avg"] = avg(gm)
    sd = std(gm)
    m["gross_margin_stability"] = -sd if sd is not None and len([x for x in gm if x is not None]) >= 3 else None
    m["gross_margin_std"] = sd
    m["ebitda_margin_avg"] = avg(ebitda_m)
    sd = std(ebitda_m)
    m["ebitda_margin_stability"] = -sd if sd is not None and len([x for x in ebitda_m if x is not None]) >= 3 else None

    # --- valutazione
    ev = mcap_fin + nd if mcap_fin is not None and nd is not None else None
    m["ev"] = ev
    m["ev_ebitda"] = div(ev, ebitda_last) if ebitda_last and ebitda_last > 0 and ev and ev > 0 else None
    m["pe"] = div(mcap_fin, ni[-1]) if ni[-1] and ni[-1] > 0 else None
    m["p_fcf"] = div(mcap_fin, fcf[-1]) if fcf[-1] and fcf[-1] > 0 else None
    m["fcf_yield"] = div(fcf[-1], mcap_fin) if mcap_fin else None
    m["pb"] = div(mcap_fin, eq) if eq and eq > 0 else None

    # multiplo storico del titolo (EV/EBITDA a fine di ogni esercizio)
    hist_mult = []
    if weekly_close is not None and len(weekly_close):
        for y, e in zip(hist[:-1], ebitda[:-1]):
            if not e or e <= 0:
                continue
            px = weekly_close[weekly_close.index <= pd.Timestamp(y["fy_end"])]
            sh = _num(y.get("shares_diluted")) or _num(y.get("shares_out"))
            ndy = _net_debt(y)
            if px.empty or not sh or ndy is None:
                continue
            mc = fx.convert(float(px.iloc[-1]) * sh, trade_ccy, fin_ccy, when=y["fy_end"])
            if mc is None or mc + ndy <= 0:
                continue
            hist_mult.append((mc + ndy) / e)
    m["ev_ebitda_hist_avg"] = avg(hist_mult) if len(hist_mult) >= 2 else None
    m["ev_ebitda_vs_own_history"] = div(m["ev_ebitda"], m["ev_ebitda_hist_avg"])

    # --- protezione
    m["beneish_m"] = beneish(hist[-1], hist[-2]) if len(hist) >= 2 else None
    m["altman_z"] = altman(last, mcap_fin)
    ca, tl = _num(last.get("current_assets")), _num(last.get("total_liabilities"))
    m["ncav"] = ca - tl if ca is not None and tl is not None else None
    m["ncav_to_mcap"] = div(m["ncav"], mcap_fin)

    # --- finanziari (banche / assicurazioni)
    m["roe"] = roe[-1]
    m["roe_avg"] = avg(roe)
    m["roe_stability"] = cv_stability(roe)
    m["roe_by_year"] = dict(zip([y["fy_end"][:4] for y in hist], roe))
    te = _tangible_equity(last)
    m["rote"] = div(ni[-1], te) if te and te > 0 else None
    rote3 = [div(_ni_adj(y), _tangible_equity(y)) for y in hist[-3:]
             if (_tangible_equity(y) or 0) > 0]
    m["rote_avg3"] = avg(rote3)
    m["ptbv"] = div(mcap_fin, te) if te and te > 0 else None
    coe = gen["cost_of_equity"]
    m["ptbv_theoretical"] = m["rote_avg3"] / coe if m["rote_avg3"] and m["rote_avg3"] > 0 else None
    m["ptbv_gap"] = div(m["ptbv"], m["ptbv_theoretical"])
    ci = [div(y.get("noninterest_expense"), y.get("revenue")) for y in hist]
    ci = [abs(x) if x is not None else None for x in ci]
    m["cost_income"] = ci[-1]
    sd = std(ci)
    m["cost_income_stability"] = -sd if sd is not None and len([x for x in ci if x is not None]) >= 3 else None
    nii = [_num(y.get("nii")) for y in hist]
    m["nii_cagr"] = cagr(nii[0], nii[-1], n)
    m["equity_to_assets"] = div(eq, last.get("total_assets"))
    m["profit_positive_share"] = share(ni_rep, lambda x: x > 0)
    m["last_year_loss"] = ni_rep[-1] is not None and ni_rep[-1] < 0

    # --- REIT
    ffo = [(_num(y.get("net_income")) + abs(_num(y.get("da"))))
           if _num(y.get("net_income")) is not None and _num(y.get("da")) is not None else None for y in hist]
    m["ffo"] = ffo[-1]
    m["ffo_cagr"] = cagr(ffo[0], ffo[-1], n)
    m["ffo_margin"] = div(ffo[-1], rev[-1])
    m["p_ffo"] = div(mcap_fin, ffo[-1]) if ffo[-1] and ffo[-1] > 0 else None
    m["debt_to_assets"] = div(last.get("total_debt"), last.get("total_assets"))

    # --- tecnica e flussi
    for key in ["rsi14", "sma50", "sma200", "dist_sma200", "high_52w", "low_52w", "dist_high_52w",
                "avg_volume_3m", "price_date", "ret_12m", "ret_6m"]:
        m[key] = tech.get(key)
    m["short_pct_float"] = _num(info.get("shortPercentOfFloat"))
    so, fl = _num(info.get("sharesOutstanding")), _num(info.get("floatShares"))
    m["free_float"] = min(div(fl, so), 1.0) if div(fl, so) is not None else None
    return m
