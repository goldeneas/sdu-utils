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

```

## 3. Configurazione

1. Copia il template dei segreti:

   ```bash
   cp .env.example .env
   ```

2. Imposta in `.env` il token Travelpayouts (obbligatorio) e il topic NTFY (per le notifiche):

   ```
   TRAVELPAYOUTS_TOKEN=il-tuo-token
   NTFY_TOPIC=mio-topic
   ```

   Riceverai le notifiche su `https://ntfy.sh/mio-topic`.

3. Regola `config.yaml` se necessario (aeroporti, soglia, finestra, ecc.).

## 4. Uso manuale

```bash
python main.py
```

Premi `Ctrl+C` in qualsiasi momento: verranno mostrati i risultati parziali
raccolti fino a quel punto.

## 5. Esecuzione pianificata

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

## 6. Verifica opzionale del type-check

```bash
.venv/bin/pip install pyright
.venv/bin/pyright scanner/ main.py
```

Con le dipendenze installate il risultato atteso è `0 errors`.

## 7. Risoluzione problemi

| Problema | Cosa fare |
|---|---|
| `Token Travelpayouts mancante/non valido` | Imposta `TRAVELPAYOUTS_TOKEN` in `.env`. |
| `nessun dato in cache` per una rotta | Rotta poco cercata su Aviasales: normale per aeroporti piccoli (BLL). Usa anche CPH. |
| Nessun volo ≤ soglia | Guarda il prezzo "più economico in assoluto" stampato per rotta e valuta di alzare `max_price`. |
| Notifiche non arrivano | Verifica `NTFY_TOPIC` in `.env` e `ntfy.enabled: true`. |
