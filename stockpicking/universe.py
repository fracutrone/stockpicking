"""Costruzione dell'universo di titoli dalle composizioni degli indici (Wikipedia).

Output: data/universe.csv con colonne ticker, index, region, country.
I ticker sono nel formato di Yahoo Finance (suffisso di borsa per l'Europa).
"""
from __future__ import annotations

import re
from io import StringIO

import pandas as pd
import requests

from .common import DATA, load_config, log

UA = {"User-Agent": "Mozilla/5.0 (compatible; stockpicking-bot/1.0; +https://github.com/fracutrone/stockpicking)"}
WIKI = "https://en.wikipedia.org/wiki/"

# (pagina wikipedia, suffisso yahoo, regione, paese, nome indice)
INDICES = [
    ("List_of_S%26P_500_companies", "", "USA", "US", "S&P 500"),
    ("List_of_S%26P_400_companies", "", "USA", "US", "S&P 400"),
    ("FTSE_MIB", ".MI", "Europa", "IT", "FTSE MIB"),
    ("DAX", ".DE", "Europa", "DE", "DAX"),
    ("MDAX", ".DE", "Europa", "DE", "MDAX"),
    ("CAC_40", ".PA", "Europa", "FR", "CAC 40"),
    ("AEX_index", ".AS", "Europa", "NL", "AEX"),
    ("IBEX_35", ".MC", "Europa", "ES", "IBEX 35"),
    ("Swiss_Market_Index", ".SW", "Europa", "CH", "SMI"),
    ("FTSE_100_Index", ".L", "Europa", "GB", "FTSE 100"),
    ("FTSE_250_Index", ".L", "Europa", "GB", "FTSE 250"),
    ("OMX_Stockholm_30", ".ST", "Europa", "SE", "OMXS30"),
    ("OMX_Copenhagen_25", ".CO", "Europa", "DK", "OMXC25"),
    ("OMX_Helsinki_25", ".HE", "Europa", "FI", "OMXH25"),
    ("OBX_Index", ".OL", "Europa", "NO", "OBX"),
    ("BEL_20", ".BR", "Europa", "BE", "BEL 20"),
    ("PSI-20", ".LS", "Europa", "PT", "PSI"),
    ("ISEQ_20", ".IR", "Europa", "IE", "ISEQ 20"),
]

TICKER_COL = re.compile(r"(ticker|symbol|epic|code)", re.I)


def _clean_ticker(raw: str, suffix: str) -> str | None:
    if not isinstance(raw, str):
        return None
    t = raw.strip().upper()
    t = re.sub(r"\[.*?\]", "", t)          # note wikipedia [1]
    if ":" in t:                            # es. "BIT: ENI"
        t = t.split(":")[-1].strip()
    t = t.split()[0] if suffix == "" else t  # USA: prende il primo token
    if not t or len(t) > 15:
        return None
    if suffix and t.endswith(suffix.upper()):
        t = t[: -len(suffix)]
    t = t.replace(" ", "-").replace("/", "-")
    if suffix:
        # classi di azioni: "BT.A" -> "BT-A", "NOVO B" -> "NOVO-B"
        t = t.rstrip(".").replace(".", "-")
    else:
        t = t.replace(".", "-")             # BRK.B -> BRK-B
    if not re.fullmatch(r"[A-Z0-9\-&]+", t):
        return None
    return t + suffix


def _fetch_index(page: str, suffix: str) -> list[str]:
    r = requests.get(WIKI + page, headers=UA, timeout=30)
    r.raise_for_status()
    tables = pd.read_html(StringIO(r.text))
    # la prima tabella con almeno 15 ticker validi è la composizione attuale
    # (le tabelle successive sono spesso lo storico delle modifiche)
    for tb in tables:
        cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in tb.columns]
        tb.columns = cols
        tcols = [c for c in cols if TICKER_COL.search(c) and "isin" not in c.lower()]
        if not tcols:
            continue
        # preferisci "ticker"/"symbol"/"epic" rispetto a un generico "code"
        tcols.sort(key=lambda c: 1 if re.search(r"code", c, re.I) else 0)
        tickers = [_clean_ticker(v, suffix) for v in tb[tcols[0]].tolist()]
        tickers = [t for t in tickers if t]
        if len(tickers) >= 15:
            return list(dict.fromkeys(tickers))
    log.warning("Pagina %s: nessuna tabella con ticker (%d tabelle, colonne: %s)", page, len(tables),
                [list(map(str, t.columns))[:6] for t in tables[:4]])
    return []


def build_universe() -> pd.DataFrame:
    cfg = load_config()
    rows = []
    for page, suffix, region, country, name in INDICES:
        try:
            tickers = _fetch_index(page, suffix)
            log.info("Indice %-10s -> %d titoli", name, len(tickers))
        except Exception as e:  # una pagina rotta non deve bloccare tutto
            log.warning("Indice %s non letto: %s", name, e)
            tickers = []
        rows += [{"ticker": t, "index": name, "region": region, "country": country} for t in tickers]

    for t in cfg.get("extra_tickers") or []:
        region = "USA" if "." not in t else "Europa"
        rows.append({"ticker": t, "index": "Extra", "region": region, "country": ""})

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("Universo vuoto: nessun indice letto")
    # un titolo può stare in più indici: tieni il primo (più importante)
    df = df.drop_duplicates("ticker", keep="first").reset_index(drop=True)

    # non perdere titoli già noti se una pagina oggi non si legge
    path = DATA / "universe.csv"
    if path.exists():
        old = pd.read_csv(path)
        failed = set(n for _, _, _, _, n in INDICES) - set(df["index"])
        keep = old[old["index"].isin(failed)]
        if len(keep):
            log.info("Recupero %d titoli dalla versione precedente (indici non letti oggi)", len(keep))
            df = pd.concat([df, keep]).drop_duplicates("ticker", keep="first")

    DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info("Universo: %d titoli (%s)", len(df), df["region"].value_counts().to_dict())
    return df
