# Stockpicking

Modello quantitativo personale per lo screening di azioni USA ed europee.
Ogni giorno lavorativo scarica dati gratuiti, calcola un punteggio su 100 e pubblica una dashboard con classifica e scheda di ogni titolo.

## Come funziona

1. **Universo**: S&P 500, S&P 400 e i principali indici europei (FTSE MIB, DAX, MDAX, CAC 40, SBF 120, AEX, IBEX 35, SMI, FTSE 100/250, nordici, BEL 20, PSI, ATX, ISEQ 20), letti da Wikipedia. Titoli aggiuntivi in `config.yaml` → `extra_tickers`.
2. **Dati**: prezzi, anagrafica, governance e bilanci da Yahoo Finance; per i titoli USA i bilanci ufficiali SEC EDGAR (fonte preferita quando ha uno storico almeno pari).
3. **Percorsi**: settori usuali, banche, assicurazioni, REIT (indicatori diversi). Biotech senza ricavi: fuori modello.
4. **Red flag**: un titolo con anche una sola red flag esce dalla classifica (resta visibile tra gli esclusi).
5. **Punteggio** (100 punti): Nucleo 30 · Valutazione 20 · Moat 20 · Macro/TAM 15 · Protezione 10 · Tecnica 5. Ogni indicatore è il percentile del titolo rispetto ai comparabili (industria se ha almeno 8 titoli, altrimenti settore). Moat e Macro sono solo statistici (5 anni, mediane dell'universo).

Pesi, soglie e parametri sono tutti in **`config.yaml`**.

## Esecuzione

Automatica con GitHub Actions (`.github/workflows/update.yml`), dal lunedì al venerdì. I bilanci si aggiornano a lotti (300 titoli per esecuzione, ogni titolo ogni 7 giorni). Avvio manuale: tab *Actions* → *Aggiornamento dati e dashboard* → *Run workflow*.

In locale:

```bash
pip install -r requirements.txt
python -m stockpicking.run                      # tutti i passi
python -m stockpicking.run --steps score        # solo ricalcolo del punteggio
```

## Limiti noti

- Dati gratuiti: per l'Europa Yahoo fornisce in genere 4 esercizi, non 5.
- Indicatori regolamentari (CET1, NPL, Solvency II, combined ratio, occupancy dei REIT) non sono nei dati standardizzati gratuiti e non entrano nel punteggio.
- Non costituisce consulenza finanziaria.
