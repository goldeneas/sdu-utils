# Ripresa flier-summary

Repository: https://github.com/goldeneas/sdu-utils
Base delle modifiche: 8ccb3ff9d99199a8870ae3fc56b1410170ba6616
Branch: `codex/flier-summary-member-offers`
Ultima ripresa: 15 novembre 2026, dal commit `356e8574b83c2adc141e6d985e7c23d5d923aa8f`.

## Obiettivo
Aggiungere al modulo flier-summary le offerte pubbliche per tutti gli iscritti Netto+ e Bilka Plus, incluse quelle fuori volantino. Escludere i coupon personali. Il progetto è una PWA statica pubblicata su GitHub Pages.

## Stato
- L'ordinamento Most recent first è già su main (8ccb3ff).
- Questo branch contiene tutte le successive modifiche sperimentali; non sono attive sul sito.
- Importatore Netto+ sperimentale nella standard library, attivabile con --netto-plus.
- Non attivo nel workflow: parser verificato su HTML rappresentativo, manca una cattura HTML reale.
- Etichette soci visibili su schede, offerte in evidenza, dettaglio, carrello salvato e prezzi ricordati dei preferiti.
- Prezzo non soci separato dal prezzo precedente: non inventare percentuali di risparmio.
- Fonte membri con snapshot e timestamp separati; fallback non proroga le scadenze.
- Identità delle offerte include condizioni; varianti e prezzi diversi non vanno persi.
- Avvisi distinguono selezione pubblica, dati salvati e fonte non disponibile.
- Passano 58 test Python (42 precedenti + 16 regressioni/diagnostica). Verifiche Playwright della sessione precedente: etichette, dettaglio, carrello persistente e avvisi. In questa ripresa non sono stati modificati UI o service worker. Controlli sintassi JS e git diff --check passati.
- Corrette tre lacune riprodotte: schede coupon personali accettate come prezzi pubblici, Date HTTP assente/futura accettata per il conto alla rovescia, e uso dell'orario iniziale del job invece dell'orario della raccolta membri dopo download volantini a cavallo di mezzanotte.
- Errori socket e Age fuori intervallo diventano fallimenti della fonte, consentendo il fallback; schede con prezzi ambigui vengono rifiutate.
- Aggiunta diagnostica `scraper/probe_member_sources.py`: cinque URL pubblici fissi, client HTTP condiviso col collector, distinzione proxy/origine, cattura HTML UTF-8 con hash e header selezionati, validazione Netto+ separata dalla raggiungibilità. Non produce un feed e non abilita il workflow.

## Accesso verificato in questa ripresa
- Configurazione osservata applicata, revisione 1: HTTP `restricted`, `allowed_hosts` vuoto. Restano soltanto i domini dei preset per pacchetti/Git.
- `curl` sui tre URL richiesti fallisce con `CONNECT tunnel failed, response 403` prima di raggiungere i siti.
- La diagnostica Python conferma `proxy-denied` per tutti e cinque gli URL (Netto+, Bilka Plus, home BilkaToGo, pagina concetto Plus e selezione `/s?query=plus`). Nessuna cattura HTML reale è stata ottenuta. Report locale: `work/member-sources/live-access/report.json` (non versionato, può non sopravvivere alla prossima chat).
- Lo strumento di ricerca legge il testo pubblico di https://netto.dk/netto-plus/, https://www.bilka.dk/plus/ e https://www.bilkatogo.dk/inspiration/om-bilka-togo/bilka-plus-koncept/. Conferma la distinzione fra prezzi soci e coupon personali, ma non fornisce l'HTML originale come fixture. La selezione BilkaToGo non è accessibile tramite questo strumento; la pagina informativa non restituisce prodotti utilizzabili.
- Il tentativo nel browser Cloud fallisce prima della navigazione con `the gaas-browser node_repl sandbox cannot be disabled`; non costituisce un test dell'accesso al sito nel browser.
- Nessun tool di modifica della policy HTTP è disponibile in questa sessione. Per proseguire sui dati reali, consentire `netto.dk`, `www.bilka.dk` e `www.bilkatogo.dk` nelle impostazioni dell'ambiente. Aggiungere altri host solo se osservati nelle risposte/richieste pubbliche; `api.bilkatogo.dk` resta un dominio candidato, non un endpoint offerte verificato. Non cambiare proxy o TLS per aggirare il blocco.

## Ripresa in una nuova chat
1. Selezionare l'ambiente aggiornato e il repository goldeneas/sdu-utils.
2. Fare fetch e checkout del branch `codex/flier-summary-member-offers`, preservando eventuali modifiche già presenti.
3. Le modifiche sono già incluse nel branch: non occorre applicare patch o allegare file.
4. Leggere le istruzioni AGENTS.md se presenti e lo stato git prima di modificare i file.
5. Eseguire `python -m unittest discover -s flier-summary/scraper -q` e `node --check flier-summary/app.js`.
6. Eseguire `python flier-summary/scraper/probe_member_sources.py --out-dir work/member-sources/check-02` (directory nuova) e leggere `report.json` prima di procedere con dati live.

## Prossimo lavoro
- Verificare accesso HTTP a https://netto.dk/netto-plus/, https://www.bilka.dk/plus/ e https://www.bilkatogo.dk/.
- Il blocco è stato riconfermato in questa ripresa. I permessi filesystem/comandi sono distinti dalla policy HTTP; finché non cambia, non ripetere indagini che richiedono richieste reali né inventare uno schema Bilka.
- Ispezionare HTML reale Netto+, correggere parser se necessario e aggiungere fixture reale; verificare date, prezzi, copertura e doppioni col volantino prima di attivare la raccolta automatica.
- Per Bilka è stato trovato il link ufficiale https://www.bilkatogo.dk/s?query=plus dalla pagina https://www.bilkatogo.dk/inspiration/om-bilka-togo/bilka-plus-koncept/. Il motore di ricerca mostra solo la struttura del sito, senza prodotti: ispezionare richieste pubbliche del sito. Nessun feed importabile è stato verificato o implementato.
- Possibile dominio API: api.bilkatogo.dk, osservato nei link ufficiali; nessun endpoint offerte individuato.
- La API Salling Anti Food Waste riguarda ribassi locali per scadenza, non tutte le offerte Plus: è fuori dall'attuale integrazione.
- Proseguire autonomamente sul lavoro autorizzato. Non dichiarare la raccolta o il deploy attivi finché non verificati.

## File modificati
- flier-summary/README.md
- flier-summary/app.js
- flier-summary/index.html
- flier-summary/scraper/fetch_offers.py
- flier-summary/sw.js
- flier-summary/scraper/member_offers.py
- flier-summary/scraper/test_member_offers.py
- flier-summary/scraper/probe_member_sources.py
- flier-summary/scraper/test_probe_member_sources.py
- flier-summary/RESUME.md
