"""Punto di ingresso: python -m stockpicking.run [--steps ...] [--limit N] [--force]

Passi:
  universe      aggiorna l'elenco dei titoli dagli indici
  prices        scarica prezzi giornalieri, settimanali e cambi
  fundamentals  aggiorna i bilanci dei titoli più vecchi (a lotti)
  score         calcola punteggi e classifica, esporta i dati della dashboard
"""
from __future__ import annotations

import argparse

import pandas as pd

from .common import DATA, log, log_to_file


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="universe,prices,fundamentals,score")
    ap.add_argument("--limit", type=int, default=None, help="titoli per lotto di bilanci")
    ap.add_argument("--force", action="store_true", help="riscarica i bilanci anche se recenti")
    ap.add_argument("--tickers", default=None, help="solo questi titoli (separati da virgola), per test")
    a = ap.parse_args()
    steps = [s.strip() for s in a.steps.split(",")]
    log_to_file(DATA / "last_run.log")

    if "esefprobe" in steps:
        from .esef_probe import run as probe
        probe()
        return
    if "diag" in steps:
        from .diag import run as diag
        diag()
        return
    if "universe" in steps:
        from .universe import build_universe
        build_universe()
    universe = pd.read_csv(DATA / "universe.csv")
    if a.tickers:
        universe = universe[universe.ticker.isin(a.tickers.split(","))]
    if "prices" in steps:
        from .prices import update_prices
        update_prices(universe.ticker.tolist())
    if "fundamentals" in steps:
        from .fundamentals import update_fundamentals
        update_fundamentals(universe, limit=a.limit, force=a.force)
    if "score" in steps:
        from .scoring import score_all
        score_all()
    log.info("Fatto: %s", ", ".join(steps))


if __name__ == "__main__":
    main()
