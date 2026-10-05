# Flight Scanner

Script Python per trovare **voli andata/ritorno convenienti** da Odense (BLL/CPH)
verso Salerno e gli aeroporti italiani più grandi, **senza usare manualmente
Skyscanner/Google Flights**.

Interroga **Google Flights via scraping** (Playwright), esplora una griglia di
date e rotte, filtra i risultati sotto una soglia di prezzo e notifica i migliori
deal su **NTFY**.

## Come funziona

1. Legge `config.yaml` (rotte, soglia, finestra di date, ecc.) e `.env` (topic NTFY).
2. Costruisce la lista di ricerche **one-way**: per ogni rotta origine→destinazione
   interroga separatamente le tratte di andata (per data di partenza) e di ritorno
   (per data di ritorno), perché Google Flights mostra una direzione alla volta.
3. Estrae dal DOM di ogni pagina i voli one-way (prezzo, compagnia, orari, scali, durata).
4. Combina in Python andata + ritorno (prezzo totale = somma delle due tratte) e
   filtra per soglia, notti minime e scali accettabili, tenendo traccia del best deal.
5. Stampa i top N risultati a terminale e invia notifiche NTFY (nuovo best deal + riepilogo).

## Specifica implementata

| Voce | Valore |
|---|---|
| Origini | BLL, CPH (configurabile) |
| Destinazioni | NAP, QSR, FCO, CIA, MXP, BGY, LIN, TRN, BLQ, PSA (configurabile) |
| Tipo viaggio | Solo andata/ritorno |
| Finestra | 30 giorni a partire da domani (configurabile) |
| Flessibilità | Tutte le partenze nella finestra (step configurabile) |
| Notti minime | 3 (configurabile) |
| Passeggeri | 1 |
| Bagaglio | Solo personal item (prezzo base mostrato da Google Flights) |
| Scali | Ammessi, durata max configurabile (best-effort) |
| Valuta | EUR |
| Soglia deal | ≤ 100 € A/R (configurabile) |
| Risultati | Top 10 (configurabile) |
| Notifiche | NTFY: nuovo best deal + riepilogo |
| Config | `config.yaml` + `.env` per i segreti |
| Piattaforme | Linux e macOS, Python 3.10+ |

## Struttura del progetto

```
flight-scanner/
├── main.py                  # entry point (CLI)
├── config.yaml              # configurazione
├── .env.example             # template per i segreti (topic NTFY)
├── requirements.txt         # dipendenze
├── pyproject.toml           # metadati + config type-check
├── README.md
├── INSTALL.md               # istruzioni di installazione e uso
└── scanner/
    ├── __init__.py
    ├── config.py            # caricamento/validazione config
    ├── models.py            # dataclass (Segment, FlightOption)
    ├── flights_client.py    # scraping Google Flights (Playwright)
    ├── search.py            # orchestrazione della griglia di ricerca
    ├── notifier.py          # notifiche NTFY
    └── output.py            # formattazione terminale
```

## Installazione e uso

Vedi **[INSTALL.md](INSTALL.md)** per il setup completo (venv, dipendenze,
browser Chromium, cron).

Uso rapido:

```bash
python main.py            # ricerca completa
python main.py --debug    # salva HTML+screenshot per manutenzione
python main.py --config altro.yaml
```

## Configurazione

Tutto in `config.yaml`:

| Chiave | Significato | Default |
|---|---|---|
| `search.max_price` | Soglia "deal" (€, A/R totale) | 100 |
| `search.top_n` | Risultati mostrati | 10 |
| `search.window_days` | Finestra di ricerca (giorni) | 30 |
| `search.min_nights` | Notti minime | 3 |
| `search.max_layover_hours` | Scalo massimo accettato | 3 |
| `search.date_step_departure` | Passo tra le date di partenza | 1 |
| `search.date_step_return` | Passo tra le date di ritorno | 1 |
| `search.max_queries` | Tetto di sicurezza (0 = illimitato) | 0 |
| `search.request_delay_seconds` | Pausa tra le query | 1.5 |
| `airports.origins` | Aeroporti di partenza | BLL, CPH |
| `airports.destinations` | Aeroporti di arrivo | NAP, QSR, … |
| `ntfy.*` | Notifiche (topic, server, ecc.) | — |
| `scraper.*` | Opzioni Playwright | — |

Il topic NTFY si imposta in `.env` (`NTFY_TOPIC=...`), non nel file versionato.

## Limitazioni note (importante)

- **Scraping fragile**: Google può cambiare il DOM di Google Flights. Se il parsing
  si rompe, esegui `python main.py --debug` e aggiorna i selettori in
  `scanner/flights_client.py` (`EXTRACT_JS`). È il punto di manutenzione previsto.
- **Prezzo "base"**: viene mostrato il prezzo più basso esposto da Google Flights,
  che per le low cost corrisponde normalmente al biglietto con solo *personal item*.
- **Prezzo = somma delle tratte one-way**: esatto per le low-cost (Ryanair, Wizz,
  easyJet prezzano per segmento), approssimato per le compagnie tradizionali (SAS,
  Lufthansa…), dove l'andata/ritorno può costare leggermente meno di due one-way.
- **Durata scalo**: è rilevata solo se Google la espone nel riepilogo della card;
  se assente, il volo viene accettato (limite non verificabile) e lo scalo è
  comunque riportato come "n scali".
- **Tempi**: la ricerca esaustiva (2 origini × 10 destinazioni × ~30 date per direzione)
  genera **~1.100 query ≈ 1-1,5 ore**. Le date/rotte senza voli vengono saltate in
  ~2s (rilevamento "nessun volo"). Per accelerare: aumenta `date_step_*` o riduci
  le destinazioni.
- **Prezzi variabili**: il prezzo può cambiare tra la ricerca e la prenotazione.

## Manutenzione (selettori scraping)

I selettori sono centralizzati in `scanner/flights_client.py`:

- `EXTRACT_JS` — estrazione dal DOM (usa gli `aria-label`, più stabili delle classi).
- `SELECTOR_CARD` — selettori delle "card" dei voli.

Quando Google cambia il markup: `python main.py --debug` salva HTML e screenshot
in `debug_dumps/`, da usare per aggiornare i selettori.
