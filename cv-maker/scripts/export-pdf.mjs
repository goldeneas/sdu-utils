// The Vite build must exist first. Generate the exact PDF served by Pages.
import { preview } from "vite";
import puppeteer from "puppeteer-core";
import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { findChrome } from "./chrome.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outFile = path.join(root, "dist", "Nicola_Picarella_CV.pdf");
const chrome = findChrome();
if (!chrome) throw new Error("Chrome/Chromium not found. Install it or set CHROME_PATH.");
if (!existsSync(path.join(root, "dist", "index.html"))) {
  throw new Error("Build the site with npm run build before exporting the PDF.");
}
// Never leave an old PDF behind when generation fails.
rmSync(outFile, { force: true });
const server = await preview({
  root,
  logLevel: "warn",
  preview: { host: "127.0.0.1", port: 0, open: false },
});
let browser;
try {
  browser = await puppeteer.launch({
    executablePath: chrome,
    headless: true,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(server.resolvedUrls.local[0], { waitUntil: "networkidle0" });
  await page.waitForSelector(".sheet .name");
  await page.evaluate(() => document.fonts.ready);
  if (errors.length) throw new Error(errors.join("\n"));
  await page.emulateMediaType("print");
  await page.pdf({
    path: outFile,
    format: "A4",
    printBackground: true,
    preferCSSPageSize: true,
  });
  console.log(`PDF written to ${path.relative(root, outFile)}`);
} catch (error) {
  rmSync(outFile, { force: true });
  throw error;
} finally {
  await browser?.close();
  await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
}
