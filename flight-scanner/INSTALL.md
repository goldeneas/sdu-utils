# Installazione e uso

## 1. Requisiti

- Python **3.10 o superiore** (testato su 3.12)
- `pip`
- Connessione internet

## 2. Setup dell'ambiente

```bash
cd flight-scanner

# ambiente virtuale
python3 -m venv .venv
source .venv/bin/activate          # macOS/Linux

# dipendenze
pip install -r requirements.txt

# browser Chromium per Playwright (una tantum)
playwright install chromium

# (solo Linux) se mancano librerie di sistema:
# playwright install-deps chromium
```

## 3. Configurazione

1. Copia il template dei segreti:

   ```bash
   cp .env.example .env
   ```

2. Imposta il topic NTFY in `.env` (obbligatorio per ricevere le notifiche):

   ```
   NTFY_TOPIC=mio-topic
   ```

   Riceverai le notifiche su `https://ntfy.sh/mio-topic`.

3. Regola `config.yaml` se necessario (aeroporti, soglia, finestra, ecc.).

## 4. Prova rapida

```bash
python main.py --debug
```

La modalità `--debug` salva HTML e screenshot di ogni ricerca in `debug_dumps/`,
utile per verificare che il parsing funzioni prima di lanciare la ricerca completa.

## 5. Uso manuale

```bash
python main.py
```

Premi `Ctrl+C` in qualsiasi momento: verranno mostrati i risultati parziali
raccolti fino a quel punto.

## 6. Esecuzione pianificata

### Linux/macOS — cron

Aggiungi a `crontab -e`, ad esempio ogni giorno alle 08:00:

```
0 8 * * * cd /percorso/flight-scanner && /percorso/flight-scanner/.venv/bin/python main.py >> /percorso/flight-scanner/cron.log 2>&1
```

### macOS — launchd (alternativa)

Crea `~/Library/LaunchAgents/com.tuo.flightscanner.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tuo.flightscanner</string>
    <key>ProgramArguments</key>
    <array>
        <string>/percorso/flight-scanner/.venv/bin/python</string>
        <string>/percorso/flight-scanner/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/percorso/flight-scanner</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>8</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/percorso/flight-scanner/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/percorso/flight-scanner/launchd.log</string>
</dict>
</plist>
```

Poi:

```bash
launchctl load ~/Library/LaunchAgents/com.tuo.flightscanner.plist
```

## 7. Verifica opzionale del type-check

```bash
.venv/bin/pip install pyright
.venv/bin/pyright scanner/ main.py
```

Con le dipendenze installate il risultato atteso è `0 errors`.

> Nota: gli import locali (`scanner.*`) e `playwright` portano un commento
> `# pyright: ignore[reportMissingImports]`. Con il `.venv` attivo si risolvono
> tutti (0 errori); il commento serve solo agli ambienti di analisi che non
> hanno le dipendenze installate o il package nel path.

## 8. Risoluzione problemi

| Problema | Cosa fare |
|---|---|
| `Google sta bloccando le richieste` | Rate-limit/captcha di Google. Aumenta `request_delay_seconds`, riduci `max_queries`, riprova più tardi. |
| `Nessun volo trovato` / parsing vuoto | Probabile cambio del DOM di Google. Esegui `python main.py --debug` e aggiorna `EXTRACT_JS` in `scanner/flights_client.py`. |
| `ricerca fallita` ripetuto | Possibile rate-limit di Google: aumenta `request_delay_seconds`, riduci `max_queries`, evita esecuzioni troppo ravvicinate. |
| Ricerca troppo lenta | Aumenta `date_step_departure`/`date_step_return`, riduci le destinazioni in `config.yaml`. |
| Notifiche non arrivano | Verifica `NTFY_TOPIC` in `.env` e che `ntfy.enabled` sia `true` in `config.yaml`. |
| `File di configurazione non trovato` | Esegui dalla root del progetto (`flight-scanner/`). |
