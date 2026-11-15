# Ripresa flier-summary

Repository: https://github.com/goldeneas/sdu-utils
Branch: `codex/flier-summary-member-offers`
Destinazione autorizzata dall'utente dopo i test: `main`.
Base su main: `8ccb3ff9d99199a8870ae3fc56b1410170ba6616`
Ultimo commit del branch all'inizio della ripresa: `02098b3`.
Ultima ripresa: 15 novembre 2026.

## Obiettivo e stato
Integrare le offerte pubbliche per tutti gli iscritti Netto+ e Bilka Plus, incluse
quelle fuori volantino, escludendo i coupon personali. La PWA resta statica su
GitHub Pages; la raccolta avviene nel workflow Python.

L'integrazione di entrambe le fonti è implementata e verificata su dati reali.
Il 15 novembre, dopo i test, l'utente ha richiesto commit e push su `main`.
Verificare il commit effettivamente presente su origin e lo stato Actions prima
di dichiarare la raccolta automatica o il deploy completati.
UI e service worker non sono cambiati in questa ripresa: le etichette soci su
schede, dettaglio, evidenza, carrello e prezzi ricordati sono quelle del branch.

## Accesso HTTP: blocco precedente superato
- Nel sandbox ordinario la diagnostica fallisce per risoluzione DNS.
- Con esecuzione autorizzata fuori sandbox i cinque URL pubblici rispondono HTTP
  200: https://netto.dk/netto-plus/, https://www.bilka.dk/plus/,
  https://www.bilkatogo.dk/, la pagina concetto Plus e `/s?query=plus`.
- Nessun proxy o controllo TLS è stato modificato. La riuscita delle richieste
  autorizzate non prova che la policy del sandbox ordinario sia cambiata.
- Report finale: `/tmp/flier-member-sources-variants-20261115/report.json`.
  Tutte le verifiche HTML e prodotti risultano `ok`; Netto ha sei offerte e
  Bilka 148. Le catture complete in /tmp sono locali e possono non sopravvivere.
- Fixture minime reali e metadati datati con URL e hash sono invece in
  `flier-summary/scraper/fixtures/` e vanno conservati con il codice.

## Netto+
Il parser precedente legge correttamente tutte le sei schede reali, inclusi
commenti React e prezzi spezzati fra elementi HTML. La fixture conserva le sei
schede `li` originali, avvolte in `ul`, senza script o altri contenuti.
Prezzi soci: 10, 9, 30, 8, 20, 10 kr.; confronti non soci: 12, 10, 35, 10, 24,
12 kr. Scadenza alla cattura del 15 novembre: 20 novembre 2026, 23:59:59 a
Copenaghen. Il prezzo non soci non è un prezzo precedente.
Restano i controlli di completezza, coupon personali, prezzi ambigui, timezone,
HTTP Date e Age. Il conto alla rovescia usa l'orario proprio della raccolta.

## Bilka Plus
- Nuovo `scraper/bilka_offers.py`, standard library, opzione `--bilka-plus`.
- Il client pubblico `https://www.bilkatogo.dk/_nuxt/86221b3.js`, osservato nella
  pagina reale, usa Algolia: app `F9VBJLR1BK`, indice
  `prod_BILKATOGO_PRODUCTS`, chiave pubblica di sola ricerca. Nessun login,
  cookie, coupon attivato o accesso al carrello.
- Endpoint verificato:
  `https://F9VBJLR1BK-dsn.algolia.net/1/indexes/prod_BILKATOGO_PRODUCTS`.
  Filtro: `cpOffer:true AND nonsearchable:false AND isInAssortmentIn:1654`.
- Store `1654` verificato tramite il client e la risposta pubblica
  `https://api.bilkatogo.dk/api/shop/v6/AvailableDeliveryAddresses?u=w&orderByZipcode=Odense`:
  Bilka Odense, Niels Bohrs Alle 150, 5230 Odense M. Il feed e le descrizioni
  esplicitano il contesto BilkaToGo/Odense, senza promettere prezzi identici in
  ogni negozio fisico o disponibilità a scaffale.
- Due pagine complete, 100 + 48 prodotti, conteggi esatti ed esaustivi.
  Date esplicite: 6–20 e 13–27 novembre 2026. Importi in øre convertiti in kr.
- `cpOfferAmount` indica il numero di confezioni del prezzo totale Mix secondo
  il componente pubblico del sito. La cattura attuale contiene solo quantità 1;
  il caso Mix è verificato con una regressione basata sul contratto del client.
- Alcuni Plus costano più della promozione ordinaria: mantenere entrambi i prezzi
  separati, senza inventare sconti. Per Mix non inventare confronti per confezione.
- Varianti Faxe Kondi possono avere nome, prezzo, formato e condizioni identici ma
  codici e immagini diversi. `sourceProductId` partecipa alla fusione: tutte le
  148 varianti restano nel feed finale. Marca e sotto-marca restano nel titolo.
- Un prodotto invalido, pagina mancante, conteggio non esaustivo, limite di 1000
  risultati, ID duplicato o totale cambiato fa fallire l'intera fonte membri.
  Il fallback separato conserva offerte, date e timestamp originali.
- API e chiave pubblica sono non documentate e possono cambiare. Usare fixture
  reali e diagnostica per correggere cambiamenti, senza schemi inventati.

## Verifiche completate
- `python3 -m unittest discover -s flier-summary/scraper -q`: 72 test passati
  (58 precedenti + 14 nuovi), con fixture reali, paginazione incompleta,
  varianti, prezzi, coupon personali, client anonimo e fallback.
- `python3 -m compileall -q flier-summary/scraper` e `git diff --check`: passati.
- Raccolta reale finale con entrambe le opzioni e `--no-translate`:
  `/tmp/flier-member-integration-final-20261115.json`.
  3.100 offerte e 3.100 ID unici: 2.946 da volantini, sei Netto+, 148 Bilka Plus.
  Tutte e cinque le fonti volantini e le due fonti membri sono `ok`.
  Conteggi finali: Netto 302, 365discount 164, Bilka 1.948,
  SuperBrugsen 150, Lidl 536.
- Il primo giro completo aveva 3.098 offerte; l'audit ha riprodotto e corretto
  la perdita di due varianti Bilka durante la fusione. La verifica finale è
  successiva alla correzione e conserva tutti i 148 prodotti.
- Nel successivo test richiesto dall'utente è stato installato Playwright solo
  in `/tmp/flier-browser-python`, con Chromium in `/tmp/flier-test-browsers`.
  Il Node incluso nel driver ha verificato `app.js`, `pwa.js` e `sw.js`.
  Nessun JS o HTML dell'app è stato modificato.
- Nuova suite ripetibile `flier-summary/tests/browser_smoke.py`: 11 test passati
  con Chromium, dati reali e profilo locale isolato. Verificati ricerca, filtri,
  ordinamento, dettaglio, immagini caricate e zoom, etichette soci, preferiti ed
  evidenza, carrello persistente, prezzi ricordati dopo scomparsa delle offerte,
  watch word, backup/ripristino, avvisi cached/unavailable, refresh HTTP 503 e
  riavvio offline con risposta del service worker. Schermate a 390 e 1440 px,
  senza overflow orizzontale; nessun errore JavaScript non gestito.
- Per il cambio lingua sono state usate traduzioni salvate in cache; il servizio
  Google non è stato testato. Guasti e offline sono scenari simulati, mentre i
  prodotti vengono dalla raccolta reale. Non sono stati testati dispositivi fisici
  o browser diversi da Chromium.
- Raccolta reale ripetuta per i test: `/tmp/flier-browser-live-20261115.json`,
  generata alle 17:24:50 UTC, con 3.100 ID unici e tutte e sette le fonti `ok`.
  Diagnostica attuale: `/tmp/flier-test-sources-20261115/report.json`.
  Report browser e schermate: `/tmp/flier-browser-results-20261115/`.
- Anche la suite Python (72 test) e `git diff --check` sono passati nuovamente.
- Il workflow esclude ora anche `flier-summary/tests` dai file pubblicati.
- Il workflow del branch passa ora `--netto-plus --bilka-plus`. Questo configura
  la futura raccolta automatica, ma non prova un deploy o un job Actions riuscito.

## Comandi di ripresa
Prima leggere stato Git e eventuali AGENTS.md, preservando i file locali.
In questa sessione esiste `python3`, non `python`.

```sh
python3 -m unittest discover -s flier-summary/scraper -q
python3 flier-summary/scraper/probe_member_sources.py --bilka-products --out-dir /tmp/member-check-NUOVO
python3 flier-summary/scraper/fetch_offers.py --netto-plus --bilka-plus --no-translate --out /tmp/member-offers-NUOVO.json
```

Per il probe usare una directory nuova. Se richieste indispensabili falliscono
nel sandbox per rete/DNS, richiedere l'esecuzione autorizzata come da permessi
dell'ambiente. Non ripetere la precedente diagnosi di proxy 403 come fatto attuale.

## Commit, push e pubblicazione
Commit e push su `main` sono stati autorizzati dopo i test; conservare codice,
fixture e suite browser insieme, integrando eventuali aggiornamenti remoti senza
force push. Il workflow Pages è programmato o avviato manualmente: un push non
prova che il sito sia aggiornato. Verificare il job Actions con entrambe le fonti,
`memberFeeds` e le etichette sul sito reale prima di dichiarare il deploy riuscito.
Non dichiarare copertura completa delle app: si raccolgono selezioni pubbliche.
