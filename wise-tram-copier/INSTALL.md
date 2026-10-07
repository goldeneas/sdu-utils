# Installing the web app

This folder is a static, installable web app (a PWA). There is nothing to build: you put the files on any
HTTPS web server, open the address on your phone or computer, and use "Install" / "Add to Home Screen".
After the first visit it works offline.

The files that make it installable are `manifest.webmanifest`, `sw.js`, `pwa.js` and `icons/`.
The screens are `index.html` (payment) and `cards.html` (cards); their data lives in `config.js`.

## 1. Put it online (needed to install)

Browsers only allow installing a web app (and its offline service worker) from **HTTPS**, or from `localhost`.
Upload the *contents of this folder* (`wise-tram-copier/`) so that `index.html` is at the top of the site.
Any static host works. Examples:

- **Netlify Drop**: go to <https://app.netlify.com/drop> and drag this folder in.
- **Cloudflare Pages / Vercel / Netlify (from Git)**: connect the repo and set the *root/publish directory*
  to `wise-tram-copier`. No build command.
- **GitHub Pages**: Pages can only publish the repo root or `/docs`, so for this subfolder use a GitHub Actions
  workflow that uploads `wise-tram-copier/` (the "Static HTML" starter workflow, with `path: wise-tram-copier`),
  or copy the folder into a separate repo.

Notes before you publish:

- The site is reachable by anyone who has the URL. It includes `assets/card-bg.jpg` (your card picture). Don't
  publish it if you don't want that picture public, or delete the file first (the page then falls back to the drawn card).
- Use relative paths only (already the case), so it also works from a sub-path such as `https://you.github.io/repo/`.

### Just trying it on your computer

```sh
cd wise-tram-copier
python3 -m http.server 8000
```

Open <http://localhost:8000/>. `localhost` counts as secure, so the install button works in Chrome/Edge.
Opening the files by double-click (`file://`) shows the pages but cannot install them.
A phone on the same Wi-Fi cannot install from `http://<your-computer-ip>:8000`, because that is not HTTPS.
Use a real host for the phone.

## 2. Install it

Open the site's address (the one ending in the folder that holds `index.html`), let it load once while online, then:

**iPhone / iPad (Safari)**
1. Open the address in **Safari** (other iOS browsers can't install it on older iOS versions).
2. Tap the **Share** button, then **Add to Home Screen**.
3. Keep the name "UI Mock" (or change it) and tap **Add**. Launch it from the new home-screen icon.

**Android (Chrome)**
1. Open the address in Chrome.
2. Tap the menu (&#8942;), then **Install app** (or **Add to Home screen**), and confirm.
3. Launch it from the app drawer or home screen.

**Windows / macOS / Linux (Chrome or Edge)**
1. Open the address.
2. Click the install icon at the right end of the address bar (or menu, then **Install ...** / **Apps**).
3. It opens in its own window and appears in your applications.

**macOS Safari 17+**: File, then **Add to Dock**.

The app opens on the payment screen (`index.html`). On Android and desktop, long-pressing / right-clicking the icon also offers a
**Cards** shortcut.

## 3. Check that it works offline

1. Open the installed app once while online.
2. Turn on airplane mode (or disconnect) and open it again. Both screens should still load.

## 4. Changing data and updating

- **Change what is shown**: edit `config.js` (see `README.md`), upload the file again, and reload the app.
  When online, `config.js` is always fetched fresh, so the change appears on the next open.
- **After changing HTML, images or other files**: bump `VERSION` at the top of `sw.js` (for example `'v3'` to `'v4'`)
  and upload. Installed copies fetch the new files on the next online visit and apply them after closing and reopening the app.
- **App name and icon** are in `manifest.webmanifest` and `icons/`. Phones read them when you install, so
  to see a new name or icon, uninstall and install again.

## 5. Uninstall

- **iOS**: press and hold the icon, then **Remove App**.
- **Android**: press and hold the icon, then **Uninstall** (or **Remove**).
- **Desktop**: in the app window, menu (&#8942;), then **Uninstall ...**.

To also clear the offline copy, clear the site's data in the browser's settings.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| No "Install" option | You're not on HTTPS (or `localhost`), or you opened it in an in-app browser. Use Safari (iOS) or Chrome/Edge. |
| Still shows old content after an update | Bump `VERSION` in `sw.js`, reload twice, or close and reopen the installed app while online. |
| Card picture missing | `assets/card-bg.jpg` wasn't uploaded, or `cards.cardImage` in `config.js` points elsewhere. The drawn card is shown instead. |
| Blank/odd page offline | Open the app once online first so the files get cached. |
| Page works on `localhost` but not when hosted | The host must serve the folder contents at the site root or a sub-path, with `index.html` and `sw.js` in the same directory. |
