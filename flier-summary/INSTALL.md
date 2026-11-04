# Installing flier-summary

## 1. Turn on GitHub Pages (once per repo)

If `wise-tram-copier` is already published, this is done. Otherwise: repo **Settings**, **Pages**, *Build and deployment*,
Source: **GitHub Actions**. Then run the workflow once (Actions, *Deploy web apps to GitHub Pages*, *Run workflow*), or push to `main`.

The app is then at `https://<user>.github.io/sdu-utils/flier-summary/`.

## 2. Install it on the phone

Open that address once while online, then:

- **iPhone (Safari)**: Share, **Add to Home Screen**, Add.
- **Android (Chrome)**: menu (&#8942;), **Install app**.

It opens full screen from the home screen. After the first visit the last downloaded offers also show offline.

## 3. Try it on your computer

```sh
python3 flier-summary/scraper/fetch_offers.py   # needs internet, creates data/offers.json
cd flier-summary && python3 -m http.server 8000
```

Open <http://localhost:8000/>.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "Could not load offers" | `data/offers.json` is missing. Check the latest *Deploy web apps* run in the Actions tab; run it again by hand. |
| A store shows 0 offers | Its flier API returned nothing for that run (between fliers, or the API changed). Look for warnings in the run log. |
| Offers look old | The status line says when they were fetched. Close and reopen the app; the workflow runs every morning. |
| Stars are gone | They are stored per browser. Use **Back up stars** regularly, and **Restore** on the new device or after clearing data. |
