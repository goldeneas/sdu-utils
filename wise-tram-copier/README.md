# wise-tram-copier

A static, single-file UI mock of a card-payment detail screen, built as a frontend exercise.

- Open `index.html` in a browser (best at phone width, ~393px).
- All data is placeholder (fictional merchant, amount, card and transaction number).
- A "UI mock · not a real payment" label is always visible.
- The header collapses into a compact title as you scroll, like the original screen.
- It is not a payment record. The "UI mock" label stays visible; the install name/icons are deliberately generic.

## Changing the data (`config.js`)

Both screens read their text from `config.js` (loaded by `render.js`). Edit a value and reload; no build step.

- Leave a key out to keep the built-in default; set it to `""` to hide that element (chip, buttons, list rows, ...).
- `payment.*` drives `index.html` (amount, currency, flag, merchant, date, card, note, transaction no., ...).
- `cards.*` drives `cards.html` (title, card name and last digits, artwork text, buttons, the "Manage card" list, tab bar, ...).
- `payment.flag` supports DK, NO, SE, FI, DE, FR, IT, NL, PL, AT, BE, IE (empty hides it).
- The banner texts are in `banner.*`.
- The installed app's name and icons are in `manifest.webmanifest`, not in `config.js`.

When online, `config.js` is always fetched fresh, so edits show on the next reload. Offline it falls back to the cached copy.

## Install as an app (PWA)

The pages are wrapped as an installable, offline-capable web app: `manifest.webmanifest`, `sw.js` (offline cache),
`pwa.js` (registers the worker) and `icons/`. Only a few `<head>` tags were added to the HTML pages.

1. Serve the folder over HTTPS (or `localhost`), e.g. `python3 -m http.server 8000` for local testing, or GitHub Pages.
2. Open it on your phone: Chrome/Android -> menu -> *Install app*; iOS Safari -> Share -> *Add to Home Screen*.
3. After the first load it works offline. Bump `VERSION` in `sw.js` when you change the pages so installed copies refresh.

## Pages

- `index.html` – payment details screen mock
- `cards.html` – cards screen mock (card artwork, quick actions, "manage card" list, floating tab bar)

## Custom card picture

`cards.html` draws a placeholder card artwork in SVG. To use a real picture instead, save any image as
`assets/card-bg.jpg` (landscape, roughly 600×380 or larger). It is cropped to fill the card and drawn over the
placeholder artwork; the fictional "demo" / "CARD" text stays on top. If the file is missing, the drawn artwork is used.
