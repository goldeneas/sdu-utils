const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { gzipSync } = require("node:zlib");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");
const root = join(__dirname, "..");
const HISTORY_FILE = "scans/20261110T031500Z-100-1.json.gz";

function snapshot(count = 137) {
  const flights = Array.from({ length: count }, (_, i) => ({
    price: 40 + i,
    currency: "EUR",
    origin: i % 2 ? "MMX" : "CPH",
    destination: i % 3 ? "FCO" : "NAP",
    departure_at: `2030-01-${String(1 + (i % 20)).padStart(2, "0")}T08:35`,
    return_at: "2030-01-28T18:00",
    return_origin: i % 3 ? "FCO" : "NAP",
    return_destination: i % 2 ? "MMX" : "CPH",
    arrival_out: "",
    arrival_back: "",
    out_stops: 0,
    in_stops: 0,
    nights: 7,
    out_duration_min: 155,
    in_duration_min: 150,
    airline: "Ryanair",
    source: "ryanair",
    link: "https://www.ryanair.com/out",
    return_link: "https://www.ryanair.com/back",
    open_jaw: false,
  }));
  return {
    schema_version: 1,
    status: "ok",
    generated_at: new Date().toISOString(),
    search: {
      origins: ["CPH", "MMX"],
      destinations: ["FCO", "NAP"],
      currency: "EUR",
      max_price: 100,
      top_n: 1,
      min_nights: 5,
      max_nights: 14,
      max_transfers: 1,
      departure_from: "2030-01-01",
      departure_to: "2030-01-31",
    },
    sources: { ryanair: { succeeded: 4, failed: 0 } },
    skipped_sources: [],
    flights,
    top: flights.slice(0, 1),
    per_airport: { NAP: flights.slice(0, 1) },
  };
}
async function until(condition) {
  for (let i = 0; i < 150; i++) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  assert(condition(), "UI did not reach the expected state");
}
function start(data = snapshot()) {
  const dom = new JSDOM(readFileSync(join(root, "index.html"), "utf8"), {
    url: "https://example.com/sdu-utils/flight-scanner/",
    runScripts: "outside-only",
  });
  const w = dom.window,
    d = w.document;
  const state = {
    data,
    history: snapshot(53),
    fail: false,
    decodedHistory: false,
  };
  Object.assign(w, {
    AbortSignal,
    Response,
    DecompressionStream,
    Blob,
    TextDecoder,
  });
  w.fetch = async (url, options) => {
    assert.equal(options.cache, "no-cache");
    if (state.fail) throw new Error("offline");
    if (url === "data/history/index.json")
      return Response.json({
        schema_version: 1,
        scans: [
          {
            file: HISTORY_FILE,
            generated_at: "2026-11-10T03:15:00Z",
            count: 53,
            complete_results: true,
          },
        ],
      });
    if (url === `data/history/${HISTORY_FILE}`)
      return state.decodedHistory
        ? Response.json(state.history)
        : new Response(gzipSync(JSON.stringify(state.history)));
    assert.equal(url, "data/flights.json");
    return Response.json(state.data);
  };
  w.eval(readFileSync(join(root, "app.js"), "utf8"));
  return {
    w,
    d,
    state,
    close: () => w.close(),
    count: () => d.querySelectorAll(".ticket").length,
    change: (id, value) => {
      d.getElementById(id).value = value;
      d.getElementById(id).dispatchEvent(new w.Event("change"));
    },
  };
}

test("all results are reachable with pagination; filters and sorting use the full set", async (t) => {
  const app = start();
  t.after(app.close);
  const { d, state, change, count } = app;
  await until(() => count() === 40);
  assert.match(
    d.getElementById("result-count").textContent,
    /137 matching round trips/,
  );
  d.getElementById("next-page").click();
  assert.match(d.getElementById("page-status").textContent, /Page 2 of 4/);
  d.getElementById("next-page").click();
  d.getElementById("next-page").click();
  assert.equal(count(), 17);
  assert(d.getElementById("next-page").disabled);
  change("origin", "MMX");
  assert.match(d.getElementById("result-count").textContent, /68 matching/);
  assert.match(d.getElementById("page-status").textContent, /Page 1 of 2/);
  change("destination", "NAP");
  assert.equal(count(), 23);
  change("sort", "date");
  const expected = state.data.flights
    .filter((f) => f.origin === "MMX" && f.destination === "NAP")
    .sort(
      (a, b) =>
        a.departure_at.localeCompare(b.departure_at) || a.price - b.price,
    );
  assert.match(
    d.querySelector(".ticket .price").textContent,
    new RegExp(String(expected[0].price)),
  );
  change("origin", "");
  change("destination", "");
  change("sort", "price");
  d.querySelector('[data-view="budget"]').click();
  assert.match(d.getElementById("result-count").textContent, /61 matching/);
  d.querySelector('[data-view="all"]').click();
  assert.match(d.getElementById("result-count").textContent, /137 matching/);
});

test("compressed history loads without a scan and retains departed flights", async (t) => {
  const app = start();
  t.after(app.close);
  const { d, state, change, count } = app;
  state.history.flights.forEach((f) => (f.departure_at = "2020-01-01T08:35"));
  await until(
    () => d.querySelectorAll("#scan option").length === 2 && count() === 40,
  );
  change("scan", HISTORY_FILE);
  await until(() =>
    d.getElementById("result-count").textContent.includes("53 matching"),
  );
  assert.equal(count(), 40);
  assert.match(d.querySelector(".ticket").textContent, /Departure has passed/);
  d.getElementById("next-page").click();
  assert.equal(count(), 13);
  change("scan", "");
  await until(() =>
    d.getElementById("result-count").textContent.includes("137 matching"),
  );
  assert.equal(count(), 40);
  state.decodedHistory = true;
  change("scan", HISTORY_FILE);
  await until(() =>
    d.getElementById("result-count").textContent.includes("53 matching"),
  );
});

test("invalid or failed refresh preserves the current set and escapes provider content", async (t) => {
  const initial = snapshot(5);
  initial.flights[0].airline = "<img src=x onerror=alert(1)>";
  initial.flights[0].link = "javascript:alert(1)";
  initial.flights[0].return_link = "";
  const app = start(initial);
  t.after(app.close);
  const { d, state, count } = app;
  await until(() => count() === 5);
  assert.equal(
    d.querySelectorAll('.ticket img, a[href^="javascript:"]').length,
    0,
  );
  assert.match(d.querySelector(".ticket").textContent, /<img src=x/);
  state.fail = true;
  d.getElementById("refresh").click();
  await until(() =>
    d.getElementById("notice").textContent.includes("Couldn’t refresh"),
  );
  assert.equal(count(), 5);
  state.fail = false;
  state.data = snapshot();
  state.data.flights[0].price = null;
  d.getElementById("refresh").click();
  await until(() => !d.getElementById("refresh").disabled);
  assert.equal(count(), 5);
});

test("old saved highlights remain accessible with an explicit completeness notice", async (t) => {
  const data = snapshot(1);
  delete data.flights;
  const app = start(data);
  t.after(app.close);
  await until(() => app.count() === 1);
  assert.match(
    app.d.getElementById("notice").textContent,
    /older scan contains only saved highlights/,
  );
});

test("service worker caches latest, history index and compressed scans without touching sibling apps", async () => {
  const scope = "https://example.com/sdu-utils/flight-scanner/",
    handlers = {},
    stores = new Map();
  const urlOf = (r) => new URL(typeof r === "string" ? r : r.url, scope).href;
  const storage = {
    open: async (name) => {
      if (!stores.has(name)) stores.set(name, new Map());
      const m = stores.get(name);
      return {
        addAll: async () => {},
        add: async () => {},
        put: async (key, res) => m.set(urlOf(key), res.clone()),
        match: async (key) => m.get(urlOf(key))?.clone(),
      };
    },
    keys: async () => [...stores.keys()],
    delete: async (name) => stores.delete(name),
  };
  let online = true;
  const context = {
    URL,
    Request,
    Response,
    AbortSignal,
    caches: storage,
    fetch: async (req) => {
      if (!online) throw new Error("offline");
      return req.url.endsWith(".gz")
        ? new Response(gzipSync(JSON.stringify(snapshot(53))))
        : Response.json(snapshot());
    },
    self: {
      registration: { scope },
      addEventListener: (type, handler) => (handlers[type] = handler),
      clients: { claim: async () => {} },
      skipWaiting: async () => {},
    },
  };
  vm.runInNewContext(readFileSync(join(root, "sw.js"), "utf8"), context);
  const request = async (path, navigate = false) => {
    let promise;
    handlers.fetch({
      request: {
        url: new URL(path, scope).href,
        method: "GET",
        mode: navigate ? "navigate" : "cors",
      },
      respondWith: (p) => (promise = p),
    });
    return promise;
  };
  assert.equal(
    (await (await request("data/flights.json")).json()).flights.length,
    137,
  );
  await request("data/history/index.json");
  const zipped = Buffer.from(
    await (await request(`data/history/${HISTORY_FILE}`)).arrayBuffer(),
  );
  online = false;
  assert.equal(
    (await (await request("data/flights.json")).json()).flights.length,
    137,
  );
  assert((await request("data/history/index.json")).ok);
  assert.deepEqual(
    Buffer.from(
      await (await request(`data/history/${HISTORY_FILE}`)).arrayBuffer(),
    ),
    zipped,
  );
  assert.equal(await request("../central-canteen/app.js"), undefined);
  await storage.open("central-canteen-v1");
  await storage.open("flight-scanner-old");
  let activation;
  handlers.activate({ waitUntil: (p) => (activation = p) });
  await activation;
  assert(stores.has("central-canteen-v1"));
  assert(!stores.has("flight-scanner-old"));
  assert(stores.has("flight-scanner-data"));
});
