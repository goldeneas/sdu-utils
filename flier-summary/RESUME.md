# Ripresa flier-summary

Repository: https://github.com/goldeneas/sdu-utils
Base delle modifiche: 8ccb3ff9d99199a8870ae3fc56b1410170ba6616

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
- Passano 42 test Python. Verifiche Playwright eseguite su preview locale: etichette, dettaglio, carrello persistente e avvisi. Controlli sintassi JS e git diff --check passati.

## Ripresa in una nuova chat
1. Selezionare l'ambiente aggiornato e il repository goldeneas/sdu-utils.
2. Fare fetch e checkout del branch `codex/flier-summary-member-offers`, preservando eventuali modifiche già presenti.
3. Le modifiche sono già incluse nel branch: non occorre applicare patch o allegare file.
4. Leggere le istruzioni AGENTS.md se presenti e lo stato git prima di modificare i file.
5. Eseguire `python -m unittest discover -s flier-summary/scraper -q` e `node --check flier-summary/app.js`.

## Prossimo lavoro
- Verificare accesso HTTP a https://netto.dk/netto-plus/, https://www.bilka.dk/plus/ e https://www.bilkatogo.dk/.
- L'ultimo ambiente restava restricted con allowed_hosts vuoto, revisione 1: tutti e tre fallivano CONNECT con 403 dal proxy. I permessi filesystem/comandi sono distinti dalla policy HTTP.
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
