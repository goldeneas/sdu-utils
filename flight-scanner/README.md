# Flight Scanner

Trova **voli andata/ritorno convenienti** da Odense (BLL) / Copenaghen (CPH) verso
Salerno e i principali aeroporti italiani, filtra per soglia di prezzo e notifica
i deal su **NTFY**.

Usa due fonti, attivabili in `config.yaml` (`sources`):

- **Travelpayouts (Aviasales) Data API**: A/R con prezzo totale da cache, una richiesta per rotta e mese.
- **Ryanair** (API tariffe non ufficiale): prezzi live per singola tratta; andata e ritorno
  vengono sommati e, con `open_jaw: true`, combinati anche su **aeroporti diversi**
  (es. andata su Roma, ritorno da Milano).

Niente scraping, niente browser.

## Come funziona

1. Legge `config.yaml` e `.env` (`TRAVELPAYOUTS_TOKEN`, `NTFY_TOPIC`).
2. Travelpayouts: per ogni rotta e per ogni mese della finestra chiama `prices_for_dates`
   (`one_way=false`, `unique=false`: tutte le combinazioni di date, non solo la migliore).
3. Ryanair: per ogni tratta (in entrambe le direzioni) e mese prende la tariffa più bassa di ogni giorno e abbina andate e ritorni.
4. Filtra: finestra di date, notti minime, scali massimi, prezzo ≤ soglia, duplicati.
5. Stampa i top N (con link di prenotazione), salva su file e invia notifiche NTFY.

## Uso

```bash
pip install -r requirements.txt
cp .env.example .env     # inserisci TRAVELPAYOUTS_TOKEN (e NTFY_TOPIC)
python main.py
python main.py --config altro.yaml
python -m pytest tests   # test (richiede pytest)
```

Il token serve solo se `sources.travelpayouts` è attivo. È gratuito: registrati su <https://www.travelpayouts.com> e copialo da
*Profilo → API token*.

## Configurazione (`config.yaml`)

| Chiave | Significato | Default |
|---|---|---|
| `search.max_price` | Soglia (€, A/R totale) | 100 |
| `search.top_n` | Risultati mostrati | 10 |
| `search.window_days` | Finestra delle partenze (giorni da domani); il ritorno può cadere oltre | 30 |
| `search.exclude_next_days` | Salta i prossimi N giorni (con `window_days: 60` e `15`: partenze dal giorno 16 al 60) | 0 |
| `search.min_nights` / `max_nights` | Notti minime / massime | 3 / 14 |
| `search.max_transfers` | Scali massimi per tratta | 1 |
| `search.request_delay_seconds` | Pausa tra le richieste | 0.5 |
| `airports.origins` / `destinations` | Codici IATA | BLL, CPH → NAP, QSR, FCO, … |
| `sources.travelpayouts` / `ryanair` | Abilita la fonte | true |
| `sources.open_jaw` | Andata/ritorno su aeroporti diversi (Ryanair) | true |
| `ntfy.*` | Notifiche | — |
| `output.*` | Salvataggio su file (csv/txt/json) | — |
| `output.top_per_airport` | Solo su file: sotto la top, i migliori N per aeroporto di arrivo, senza soglia di prezzo (0 = off) | 3 |

## Limitazioni

- **Ryanair**: l'endpoint è non ufficiale e può cambiare o limitare le richieste; solo voli Ryanair, prezzo base senza bagagli. Le combinazioni open-jaw sono due biglietti separati (due link).

- **Prezzi da cache**: Travelpayouts restituisce i prezzi trovati di recente dagli
  utenti Aviasales, non una ricerca live. Possono essere scaduti: verifica sempre
  dal link prima di prenotare. Il prezzo è quello base, tipicamente senza bagaglio.
- **Copertura**: gli aeroporti piccoli (es. BLL) hanno meno dati in cache; CPH è
  molto più coperto. Per ogni rotta lo script stampa anche il prezzo A/R più basso
  trovato in assoluto, così si vede se la soglia è semplicemente troppo bassa.
- **Soglia realistica**: ≤ 100 € A/R verso l'Italia dalla Danimarca è raro; se
  non esce nulla, prova ad alzare `max_price` o `window_days`.
