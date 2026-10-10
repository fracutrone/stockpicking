"""Sonda: verifica dal server di GitHub che GLEIF e filings.xbrl.org rispondano e come."""
from __future__ import annotations

import json

import requests

from .common import log

UA = {"User-Agent": "stockpicking research github.com/fracutrone/stockpicking", "Accept": "application/vnd.api+json"}


def _get(url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=40, **kw)
        log.info("PROBE GET %s -> %s (%d byte)", r.url[:160], r.status_code, len(r.content))
        return r
    except Exception as e:
        log.info("PROBE GET %s -> ERR %s", url[:160], e)
        return None


def run() -> None:
    # 1) GLEIF: ricerca per nome
    r = _get("https://api.gleif.org/api/v1/lei-records", params={"filter[entity.legalName]": "Eni S.p.A.", "page[size]": 3})
    lei = None
    if r is not None and r.ok:
        d = r.json().get("data", [])
        for x in d:
            log.info("PROBE GLEIF %s %s", x["id"], x["attributes"]["entity"]["legalName"]["name"])
        lei = d[0]["id"] if d else None
    # GLEIF per ISIN
    r = _get("https://api.gleif.org/api/v1/lei-records", params={"filter[isin]": "IT0003132476"})
    if r is not None and r.ok:
        d = r.json().get("data", [])
        log.info("PROBE GLEIF isin -> %s", [x["id"] for x in d])
        lei = lei or (d[0]["id"] if d else None)
    if not lei:
        return
    # 2) filings.xbrl.org: entità per LEI
    for url in [f"https://filings.xbrl.org/api/entities?filter[identifier]={lei}",
                f"https://filings.xbrl.org/api/entities/{lei}",
                f"https://filings.xbrl.org/api/filings?filter[entity.identifier]={lei}&include=entity",
                f"https://filings.xbrl.org/api/entities/{lei}/filings"]:
        r = _get(url)
        if r is not None and r.ok:
            try:
                j = r.json()
                data = j.get("data")
                sample = data[:2] if isinstance(data, list) else data
                log.info("PROBE  risposta: %s", json.dumps(sample)[:900])
            except Exception as e:
                log.info("PROBE  non JSON: %s", e)
    # 3) ultimo bilancio e fatti xBRL-JSON
    r = _get(f"https://filings.xbrl.org/api/entities/{lei}/filings")
    if r is None or not r.ok:
        return
    fil = sorted(r.json().get("data", []), key=lambda x: x["attributes"].get("period_end") or "")
    if not fil:
        return
    last = fil[-1]["attributes"]
    log.info("PROBE ultimo filing: period_end=%s json_url=%s", last.get("period_end"), last.get("json_url"))
    if last.get("json_url"):
        r = _get("https://filings.xbrl.org" + last["json_url"])
        if r is not None and r.ok:
            facts = r.json().get("facts", {})
            n = 0
            for fid, f in facts.items():
                c = f.get("dimensions", {}).get("concept", "")
                if c in ("ifrs-full:Revenue", "ifrs-full:ProfitLoss", "ifrs-full:Equity", "ifrs-full:Assets") \
                        and len(f.get("dimensions", {})) <= 4:
                    log.info("PROBE  fatto %s %s %s %s", c, f.get("value"), f["dimensions"].get("period"),
                             f["dimensions"].get("unit"))
                    n += 1
                    if n > 12:
                        break
