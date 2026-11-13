# cv-maker

CV di Nicola Picarella, in sola lettura, con download diretto del PDF:
<https://goldeneas.github.io/sdu-utils/cv-maker/>.

Il modulo conserva dati, struttura e stile del progetto `cv-maker-main.zip` allegato.
Non contiene editor, upload o salvataggio dal browser. Il pulsante **Scarica CV (PDF)**
scarica `Nicola_Picarella_CV.pdf`, senza aprire una finestra di stampa.

## Pubblicazione

Il workflow condiviso `.github/workflows/deploy-pages.yml` ricostruisce il sito e
rigenera il PDF da `cv.json` a ogni deploy giornaliero (03:15 UTC), oppure avviandolo
da **Actions → Deploy web apps to GitHub Pages → Run workflow**.
Il PDF viene prodotto con Chromium dalla stessa pagina e dagli stessi stili A4 del CV;
la barra di download viene esclusa dalla stampa. Il contenuto non viene riscritto.

Il workflow esegue typecheck, build e test di download prima della pubblicazione,
copiando solo `dist/` in `_site/cv-maker/`, insieme a tutti gli altri moduli.
Non serve un secondo workflow Pages. Un errore di generazione o nei test interrompe
la pubblicazione, lasciando disponibile il precedente deploy.

Per aggiornare il CV, il proprietario modifica `cv-maker/cv.json` nel repository;
il deploy successivo aggiorna pagina e PDF. Nessuna modifica è disponibile sul sito.

## Sviluppo e test

Richiede Node.js 24 e Chrome/Chromium. In CI si riutilizza il Chromium già installato
dal workflow per il menu della mensa. In locale si rilevano i percorsi standard;
`CHROME_PATH` consente di indicare un eseguibile diverso.

```sh
cd cv-maker
npm ci
npm run dev        # anteprima; il PDF è disponibile nella build di produzione
npm run build      # typecheck, sito e dist/Nicola_Picarella_CV.pdf
npm test           # test della build con un browser reale
```

`npm run pdf` esegue la stessa build completa. `dist/` e `node_modules/` sono ignorati
da Git. I test avviano il sito sotto `/sdu-utils/cv-maker/` e `/cv-maker/`, cliccano il
download e confrontano il file salvato con il PDF pubblicato; verificano inoltre
l'assenza di controlli di modifica, gli asset, i layout mobile/desktop e lo stile di stampa.
