import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import puppeteer from "puppeteer-core";
import { preview } from "vite";
import { findChrome } from "../scripts/chrome.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const filename = "Nicola_Picarella_CV.pdf";
const cv = JSON.parse(await readFile(path.join(root, "cv.json"), "utf8"));

for (const base of ["/sdu-utils/cv-maker/", "/cv-maker/"]) {
  test(`Read-only CV and real PDF download at ${base}`, { timeout: 30000 }, async t => {
    const directory = await mkdtemp(path.join(tmpdir(), "cv-maker-download-"));
    t.after(() => rm(directory, { recursive: true, force: true }));
    const server = await preview({
      root, base, logLevel: "silent",
      preview: { host: "127.0.0.1", port: 0, open: false },
    });
    t.after(() => new Promise(resolve => server.httpServer.close(resolve)));
    const browser = await puppeteer.launch({
      executablePath: findChrome(), headless: true, args: ["--no-sandbox"],
    });
    t.after(() => browser.close());
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => {
      if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
    });
    const response = await page.goto(server.resolvedUrls.local[0], { waitUntil: "networkidle0" });
    assert.equal(response.status(), 200);
    await page.waitForSelector(".sheet .name");
    assert.equal(await page.$eval(".name", node => node.textContent), cv.basics.name);
    assert.equal(await page.$$eval("input, textarea, select, [contenteditable]:not([contenteditable=false])", nodes => nodes.length), 0);

    // A same-origin relative URL must work under the actual Pages project prefix.
    const link = await page.$eval("a[download]", node => ({ href: node.href, name: node.download }));
    assert.equal(new URL(link.href).pathname, `${base}${filename}`);
    assert.equal(link.name, filename);
    const pdf = await fetch(link.href);
    assert.equal(pdf.status, 200);
    assert.match(pdf.headers.get("content-type"), /application\/pdf/);
    const expected = await readFile(path.join(root, "dist", filename));
    assert.equal(expected.subarray(0, 5).toString(), "%PDF-");
    assert.ok(expected.length > 10000, "The generated CV must contain a real PDF");
    assert.deepEqual(Buffer.from(await pdf.arrayBuffer()), expected);

    const session = await browser.target().createCDPSession();
    await session.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: directory });
    await page.click("a[download]");
    let downloaded;
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      try {
        downloaded = await readFile(path.join(directory, filename));
        if (downloaded.equals(expected)) break;
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      await delay(100);
    }
    assert.deepEqual(downloaded, expected, "Clicking must save the complete published PDF");
    assert.equal(new URL(page.url()).pathname, base, "Downloading keeps the CV page open");

    for (const width of [375, 1440]) {
      await page.setViewport({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `No horizontal overflow at ${width}px`);
      const button = await page.$eval("a[download]", node => {
        const r = node.getBoundingClientRect();
        return { width: r.width, height: r.height, right: r.right, left: r.left };
      });
      assert.ok(button.width >= 44 && button.height >= 44 && button.left >= 0 && button.right <= width, `Accessible download target at ${width}px: ${JSON.stringify(button)}`);
    }
    await page.emulateMediaType("print");
    assert.equal(await page.$eval(".download-bar", node => getComputedStyle(node).display), "none");
    assert.notEqual(await page.$eval(".sheet", node => getComputedStyle(node).display), "none");
    assert.deepEqual(errors, [], "The deployed app must load without browser or HTTP errors");
  });
}
