# Stockpicking

Modello quantitativo personale per lo screening di azioni USA ed europee.
Ogni giorno lavorativo scarica dati gratuiti, calcola un punteggio su 100 e pubblica una dashboard con classifica e scheda di ogni titolo.

## Come funziona

1. **Universo**: S&P 500, S&P 400 e i principali indici europei (FTSE MIB, DAX, MDAX, CAC 40, SBF 120, AEX, IBEX 35, SMI, FTSE 100/250, nordici, BEL 20, PSI, ATX, ISEQ 20), letti da Wikipedia. Titoli aggiuntivi in `config.yaml` → `extra_tickers`.
2. **Dati**: prezzi, anagrafica, governance e bilanci da Yahoo Finance; per i titoli USA i bilanci ufficiali SEC EDGAR (fonte preferita quando ha uno storico almeno pari).
3. **Percorsi**: settori usuali, banche, assicurazioni, REIT (indicatori diversi). Biotech senza ricavi: fuori modello.
4. **Red flag**: un titolo con anche una sola red flag esce dalla classifica (resta visibile tra gli esclusi).
5. **Punteggio** (100 punti): Nucleo 30 · Valutazione 20 · Moat 20 · Macro/TAM 15 · Protezione 10 · Tecnica 5. Ogni indicatore è il percentile del titolo rispetto ai comparabili (industria se ha almeno 8 titoli, altrimenti settore). Moat e Macro sono solo statistici (5 anni, mediane dell'universo).

6. **Utili rettificati**: P/E, margini, ROE ed EV/EBITDA usano utile ed EBITDA al netto delle voci straordinarie (svalutazioni, plusvalenze una tantum).
7. **Controprova dei dati**: i bilanci di Yahoo sono confrontati con la fonte ufficiale (SEC per gli USA; bilanci digitali ESEF da filings.xbrl.org, con codice LEI da GLEIF, per l'Europa). Se attivo, patrimonio o utile divergono oltre la tolleranza il titolo esce dalla classifica come "dati da verificare"; se i ricavi coincidono e il resto no, è segnalato come "principi contabili diversi".
8. **Value trap**: avviso per i titoli economici con ricavi o utili in calo in un settore che il mercato sta penalizzando (rendimento 12 mesi del settore sotto la mediana). Esclusi dal portafoglio modello.
9. **Segnali di uscita**: red flag, uscita dalle prime 100, calo del punteggio di 15 punti, sconto sui multipli esaurito.
10. **Portafoglio modello**: 20 titoli dalla classifica divisi in Conviction (50%), Protective (30%), Cyclical (20%), massimo 3 per settore e 40% per paese. `my_portfolio` in `config.yaml` monitora i tuoi titoli con gli stessi segnali.
11. **Storico del modello**: ogni mese salva la classifica e misura il rendimento di top 30 e portafoglio modello contro l'universo e l'MSCI World.

Le stime degli analisti (prezzo obiettivo, giudizio, P/E atteso) sono mostrate nella scheda solo come informazione e non entrano nel punteggio.

Pesi, soglie e parametri sono tutti in **`config.yaml`**.

## Esecuzione

Automatica con GitHub Actions (`.github/workflows/update.yml`): prezzi e punteggio ogni giorno lavorativo; il 2 di ogni mese controllo dei bilanci, riscaricati solo per le società che hanno pubblicato un nuovo bilancio annuale (USA: nuovo 10-K alla SEC; Europa: esercizio chiuso da più di 14 mesi). Avvio manuale: tab *Actions* → *Aggiornamento dati e dashboard* → *Run workflow*.

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
