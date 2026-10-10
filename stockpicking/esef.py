"""Controprova europea: bilanci ufficiali ESEF/UKSEF da filings.xbrl.org (XBRL International).

Percorso: nome società -> codice LEI (GLEIF, registro ufficiale) -> ultimo bilancio digitale depositato
-> voci chiave (attivo, patrimonio netto, utile, ricavi) da confrontare con Yahoo.
Il collegamento ticker -> LEI viene salvato in data/lei_map.json per non ripetere la ricerca.
"""
from __future__ import annotations

import re
import time

import requests

from .common import DATA, log, read_json, write_json

API_HEAD = {"User-Agent": "stockpicking research github.com/fracutrone/stockpicking",
            "Accept": "application/vnd.api+json"}
JSON_HEAD = {"User-Agent": API_HEAD["User-Agent"], "Accept": "application/json"}
LEI_MAP = DATA / "lei_map.json"
BASE = "https://filings.xbrl.org"

CONCEPTS = {
    "total_assets": ["ifrs-full:Assets"],
    "equity": ["ifrs-full:EquityAttributableToOwnersOfParent", "ifrs-full:Equity"],
    "net_income": ["ifrs-full:ProfitLossAttributableToOwnersOfParent", "ifrs-full:ProfitLoss"],
    "revenue": ["ifrs-full:Revenue", "ifrs-full:RevenueFromContractsWithCustomers"],
}

_SUFFIX = re.compile(r"\b(s\.?p\.?a\.?|s\.?a\.?|n\.?v\.?|se|ag|plc|ab|asa|a/s|oyj|holding|group|ltd|limited|"
                     r"inc|corp|kgaa|co|the)\b", re.I)


def _norm(name: str) -> str:
    n = _SUFFIX.sub(" ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def _get(url, head=API_HEAD, **kw):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=head, timeout=90, **kw)
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            return r
        except Exception as e:
            log.debug("ESEF %s: %s", url, e)
            time.sleep(3)
    return None


def _filings(lei: str) -> list[dict]:
    r = _get(f"{BASE}/api/entities/{lei}/filings")
    if r is None or not r.ok:
        return []
    return [x["attributes"] for x in r.json().get("data", [])]


def find_lei(ticker: str, name: str, country: str) -> str | None:
    from datetime import date, timedelta
    cache = read_json(LEI_MAP, {}) or {}
    hit = cache.get(ticker)
    if isinstance(hit, dict):
        if hit.get("lei"):
            return hit["lei"]
        # ricerca fallita: si riprova dopo 90 giorni
        if date.fromisoformat(hit.get("date", "2000-01-01")) > date.today() - timedelta(days=90):
            return None
    lei = None
    target = _norm(name)
    base = re.sub(r"\s+", " ", _SUFFIX.sub(" ", name or "")).strip(" ,.")
    searches = [{"filter[entity.legalName]": name}, {"filter[fulltext]": name}]
    if base and base.lower() != (name or "").lower():
        searches.append({"filter[fulltext]": base})
    # terza via: ricerca approssimata di GLEIF sul nome
    r = _get("https://api.gleif.org/api/v1/fuzzycompletions", params={"field": "entity.legalName", "q": name})
    fuzzy = []
    if r is not None and r.ok:
        for x in r.json().get("data", [])[:8]:
            rel = x.get("relationships", {}).get("lei-records", {}).get("data", {})
            if rel.get("id"):
                fuzzy.append(rel["id"])
    tried = []
    for q in searches:
        params = {**q, "page[size]": 50}
        if country:
            params["filter[entity.legalAddress.country]"] = country
        r = _get("https://api.gleif.org/api/v1/lei-records", **{"params": params})
        if r is None or not r.ok:
            continue
        cands = r.json().get("data", [])
        # prima i nomi uguali a quello di Yahoo (senza forma societaria), poi i più corti
        cands.sort(key=lambda x: (_norm(x["attributes"]["entity"]["legalName"]["name"]) != target,
                                  len(x["attributes"]["entity"]["legalName"]["name"])))
        for c in cands[:6]:
            tried.append(c["attributes"]["entity"]["legalName"]["name"])
            if _filings(c["id"]):
                lei = c["id"]
                break
        if lei:
            break
    if not lei:
        for cid in fuzzy:
            if _filings(cid):
                lei = cid
                break
    if not lei:
        log.info("ESEF: LEI non trovato per %s (%s, %s); candidati GLEIF provati: %s",
                 ticker, name, country, tried[:6])
    cache[ticker] = {"lei": lei or "", "date": date.today().isoformat()}
    write_json(LEI_MAP, cache)
    return lei


def _pick(facts: dict, concepts: list[str], period_end: str) -> tuple[float | None, str | None]:
    for concept in concepts:
        best = None
        for f in facts.values():
            d = f.get("dimensions", {})
            if d.get("concept") != concept:
                continue
            extra = set(d) - {"concept", "entity", "period", "unit", "language"}
            if extra:                     # solo il dato consolidato, senza dimensioni di dettaglio
                continue
            per = d.get("period", "")
            end = per.split("/")[-1][:10]
            # istantaneo: data di chiusura (o il giorno dopo); durata: fine periodo
            if end not in (period_end, _next_day(period_end)):
                continue
            try:
                best = (float(f["value"]), (d.get("unit") or "").split(":")[-1])
            except (TypeError, ValueError):
                continue
            break
        if best:
            return best
    return None, None


def _next_day(d: str) -> str:
    from datetime import date, timedelta
    try:
        return (date.fromisoformat(d) + timedelta(days=1)).isoformat()
    except ValueError:
        return d


def official_figures(ticker: str, name: str, country: str, year_ends: list[str] | None = None) -> dict | None:
    """Voci chiave dell'ultimo bilancio ANNUALE ufficiale depositato, o None se non trovato.
    year_ends: date di chiusura degli esercizi note (da Yahoo) per scartare le semestrali."""
    lei = find_lei(ticker, name, country)
    if not lei:
        return None
    fil = [f for f in _filings(lei) if f.get("json_url") and f.get("period_end")]
    if year_ends:
        mmdd = {e[5:10] for e in year_ends}
        fil = [f for f in fil if f["period_end"][5:10] in mmdd]
    if not fil:
        return None
    last = max(fil, key=lambda f: (f["period_end"], f.get("date_added") or ""))
    r = _get(BASE + last["json_url"], head=JSON_HEAD)
    if r is None or not r.ok:
        return None
    try:
        facts = r.json().get("facts", {})
    except ValueError:
        return None
    pe = last["period_end"][:10]
    out = {"lei": lei, "period_end": pe, "source": "ESEF " + (last.get("country") or "")}
    for k, concepts in CONCEPTS.items():
        v, unit = _pick(facts, concepts, pe)
        out[k] = v
        if unit:
            out["currency"] = unit
    return out
