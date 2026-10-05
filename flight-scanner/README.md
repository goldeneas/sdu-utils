# Flight Scanner

Trova **voli andata/ritorno convenienti** da Odense (BLL) / Copenaghen (CPH) verso
Salerno e i principali aeroporti italiani, filtra per soglia di prezzo e notifica
i deal su **NTFY**.

Usa la **Travelpayouts (Aviasales) Data API**: una richiesta per rotta e mese
restituisce già tutte le combinazioni A/R con prezzo totale. Niente scraping,
niente browser: ~20 destinazioni-mese invece di ~1.100 pagine da caricare.

## Come funziona

1. Legge `config.yaml` e `.env` (`TRAVELPAYOUTS_TOKEN`, `NTFY_TOPIC`).
2. Per ogni rotta e per ogni mese della finestra chiama `prices_for_dates`
   (`one_way=false`, `unique=false`: tutte le combinazioni di date, non solo la migliore).
3. Filtra: finestra di date, notti minime, scali massimi, prezzo ≤ soglia, duplicati.
4. Stampa i top N (con link di prenotazione), salva su file e invia notifiche NTFY.

## Uso

```bash
pip install -r requirements.txt
cp .env.example .env     # inserisci TRAVELPAYOUTS_TOKEN (e NTFY_TOPIC)
python main.py
python main.py --config altro.yaml
python -m pytest tests   # test (richiede pytest)
```

Il token è gratuito: registrati su <https://www.travelpayouts.com> e copialo da
*Profilo → API token*.

## Configurazione (`config.yaml`)

| Chiave | Significato | Default |
|---|---|---|
| `search.max_price` | Soglia (€, A/R totale) | 100 |
| `search.top_n` | Risultati mostrati | 10 |
| `search.window_days` | Finestra di ricerca (giorni da domani) | 30 |
| `search.min_nights` | Notti minime | 3 |
| `search.max_transfers` | Scali massimi per tratta | 1 |
| `search.request_delay_seconds` | Pausa tra le richieste | 0.5 |
| `airports.origins` / `destinations` | Codici IATA | BLL, CPH → NAP, QSR, FCO, … |
| `ntfy.*` | Notifiche | — |
| `output.*` | Salvataggio su file (csv/txt/json) | — |

## Limitazioni

- **Prezzi da cache**: Travelpayouts restituisce i prezzi trovati di recente dagli
  utenti Aviasales, non una ricerca live. Possono essere scaduti: verifica sempre
  dal link prima di prenotare. Il prezzo è quello base, tipicamente senza bagaglio.
- **Copertura**: gli aeroporti piccoli (es. BLL) hanno meno dati in cache; CPH è
  molto più coperto. Per ogni rotta lo script stampa anche il prezzo A/R più basso
  trovato in assoluto, così si vede se la soglia è semplicemente troppo bassa.
- **Soglia realistica**: ≤ 100 € A/R verso l'Italia dalla Danimarca è raro; se
  non esce nulla, prova ad alzare `max_price` o `window_days`.
