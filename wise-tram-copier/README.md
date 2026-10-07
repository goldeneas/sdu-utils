# wise-tram-copier

A static, single-file UI mock of a card-payment detail screen, built as a frontend exercise.

- Open `index.html` in a browser (best at phone width, ~393px).
- All data is placeholder (fictional merchant, amount, card and transaction number).
- A "UI mock · not a real payment" label is always visible.
- The header collapses into a compact title as you scroll, like the original screen.
- It is not an installable app and is not a payment record.

## Pages

- `index.html` – payment details screen mock
- `cards.html` – cards screen mock (card artwork, quick actions, "manage card" list, floating tab bar)

## Custom card picture

`cards.html` draws a placeholder card artwork in SVG. To use a real picture instead, save any image as
`assets/card-bg.jpg` (landscape, roughly 600×380 or larger). It is cropped to fill the card and drawn over the
placeholder artwork; the fictional "demo" / "CARD" text stays on top. If the file is missing, the drawn artwork is used.
