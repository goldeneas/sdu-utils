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
function start(data = snapshot(), preferences) {
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
    details: new Map(),
    requests: [],
  };
  Object.assign(w, {
    AbortSignal,
    Response,
    DecompressionStream,
    Blob,
    TextDecoder,
  });
  w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  w.HTMLDialogElement.prototype.close = function () { this.open = false; };
  w.fetch = async (url, options) => {
    assert.equal(options.cache, "no-cache");
    state.requests.push(url);
    if (state.details.has(url)) {
      if (state.fail) throw new Error("offline");
      if (state.detailsWait) await state.detailsWait;
      const rows = state.details.get(url);
      return new Response(gzipSync(JSON.stringify(rows)));
    }
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
    if (url === `data/browser/history/${HISTORY_FILE.slice("scans/".length).replace(/\.gz$/, "")}`)
      return state.decodedHistory
        ? Response.json(state.history)
        : Response.json(state.history);
    assert.equal(url, "data/browser/latest.json");
    return Response.json(state.data);
  };
  if (preferences) w.localStorage.setItem("flight-scanner-weekends", JSON.stringify(preferences));
  w.eval(readFileSync(join(root, "app.js"), "utf8"));
  return {
    w,
    d,
    state,
    close: () => w.close(),
    count: () => Number((d.getElementById("result-count").textContent.match(/([\d,]+) matching round trips/)?.[1] || "0").replaceAll(",", "")),
    change: (id, value) => {
      d.getElementById(id).value = value;
      d.getElementById(id).dispatchEvent(new w.Event("change"));
    },
  };
}

function manyPairs() {
  const data = snapshot();
  data.flights.forEach((f, i) => {
    f.departure_at = new Date(Date.UTC(2030, 0, 1 + i)).toISOString().slice(0, 16);
    f.return_at = new Date(Date.UTC(2030, 0, 8 + i)).toISOString().slice(0, 16);
  });
  return data;
}

test("all results are reachable with pagination; filters and sorting use the full set", async (t) => {
  const app = start(manyPairs());
  t.after(app.close);
  const { d, state, change, count } = app;
  await until(() => count() === 137);
  assert.match(
    d.getElementById("result-count").textContent,
    /137 matching round trips/,
  );
  d.getElementById("next-page").click();
  assert.match(d.getElementById("page-status").textContent, /Page 2 of 4/);
  d.getElementById("next-page").click();
  d.getElementById("next-page").click();
  assert.equal(d.querySelectorAll(".date-group").length, 17);
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
    d.querySelector(".date-group .price").textContent,
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

test("compact history loads without a scan and retains departed flights", async (t) => {
  const app = start();
  t.after(app.close);
  const { d, state, change, count } = app;
  state.history.flights.forEach((f) => (f.departure_at = "2020-01-01T08:35"));
  await until(
    () => d.querySelectorAll("#scan option").length === 2 && count() === 137,
  );
  change("scan", HISTORY_FILE);
  await until(() =>
    d.getElementById("result-count").textContent.includes("53 matching"),
  );
  assert.equal(count(), 53);
  assert.equal(d.querySelectorAll(".date-group").length, 1);
  assert.match(d.querySelector(".date-group").textContent, /Departure has passed/);
  change("scan", "");
  await until(() =>
    d.getElementById("result-count").textContent.includes("137 matching"),
  );
  assert.equal(count(), 137);
  state.decodedHistory = true;
  change("scan", HISTORY_FILE);
  await until(() =>
    d.getElementById("result-count").textContent.includes("53 matching"),
  );
});

test("all four airport selectors combine with direct-only filtering on both legs", async (t) => {
  const data = snapshot(8);
  const combinations = [
    ["CPH", "FCO", "NAP", "MMX", 0, 0],
    ["CPH", "FCO", "NAP", "CPH", 0, 0],
    ["CPH", "FCO", "FCO", "MMX", 0, 0],
    ["CPH", "NAP", "NAP", "MMX", 0, 0],
    ["MMX", "FCO", "NAP", "MMX", 0, 0],
    ["CPH", "FCO", "NAP", "MMX", 1, 0],
    ["CPH", "FCO", "NAP", "MMX", 0, 1],
    ["CPH", "FCO", "NAP", "MMX", 0, null],
  ];
  data.flights.forEach((flight, i) => {
    [
      flight.origin,
      flight.destination,
      flight.return_origin,
      flight.return_destination,
      flight.out_stops,
      flight.in_stops,
    ] = combinations[i];
    flight.open_jaw =
      flight.return_origin !== flight.destination ||
      flight.return_destination !== flight.origin;
  });
  const app = start(data);
  t.after(app.close);
  const { d, w, change, count } = app;
  await until(() => count() === 8);
  change("origin", "CPH");
  assert.equal(count(), 7);
  change("destination", "FCO");
  assert.equal(count(), 6);
  change("return-origin", "NAP");
  assert.equal(count(), 5);
  change("return-destination", "MMX");
  assert.equal(count(), 4);
  const direct = d.getElementById("direct-only");
  direct.checked = true;
  direct.dispatchEvent(new w.Event("change"));
  assert.equal(count(), 1);
  assert.match(d.querySelector(".date-group .price").textContent, /40/);
  direct.checked = false;
  direct.dispatchEvent(new w.Event("change"));
  assert.equal(count(), 4);
  assert.equal(data.flights.length, 8);
});

test("return airport choices come from archived results and filters reset pagination", async (t) => {
  const app = start(manyPairs());
  t.after(app.close);
  const { d, w, state, change, count } = app;
  state.history.flights.forEach((flight) => {
    flight.return_origin = "QSR";
    flight.return_destination = "BLL";
  });
  await until(
    () => d.querySelectorAll("#scan option").length === 2 && count() === 137,
  );
  d.getElementById("next-page").click();
  assert.match(d.getElementById("page-status").textContent, /Page 2 of 4/);
  d.getElementById("direct-only").checked = true;
  d.getElementById("direct-only").dispatchEvent(new w.Event("change"));
  assert.match(d.getElementById("page-status").textContent, /Page 1 of 4/);
  change("scan", HISTORY_FILE);
  await until(() =>
    d.getElementById("result-count").textContent.includes("53 matching"),
  );
  assert(
    [...d.getElementById("return-origin").options].some(
      (option) => option.value === "QSR",
    ),
  );
  assert(
    [...d.getElementById("return-destination").options].some(
      (option) => option.value === "BLL",
    ),
  );
  change("return-origin", "QSR");
  change("return-destination", "BLL");
  assert.match(d.getElementById("result-count").textContent, /53 matching/);
  assert(d.getElementById("direct-only").checked);
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
  assert.match(d.querySelector(".date-group").textContent, /<img src=x/);
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
  const fetched = [];
  const prefetched = [];
  const urlOf = (r) => new URL(typeof r === "string" ? r : r.url, scope).href;
  const storage = {
    open: async (name) => {
      if (!stores.has(name)) stores.set(name, new Map());
      const m = stores.get(name);
      return {
        addAll: async () => {},
        add: async (key) => prefetched.push(urlOf(key)),
        put: async (key, res) => m.set(urlOf(key), res.clone()),
        match: async (key) => m.get(urlOf(key))?.clone(),
        delete: async (key) => m.delete(urlOf(key)),
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
      fetched.push(req.url);
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
  let installation;
  handlers.install({ waitUntil: (p) => (installation = p) });
  await installation;
  assert(prefetched.some((url) => url.endsWith("data/browser/latest.json")));
  assert(!prefetched.some((url) => url.endsWith("data/flights.json")));
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
    (await (await request("data/browser/latest.json")).json()).flights.length,
    137,
  );
  await request("data/history/index.json");
  const zipped = Buffer.from(
    await (await request(`data/history/${HISTORY_FILE}`)).arrayBuffer(),
  );
  online = false;
  assert.equal(
    (await (await request("data/browser/latest.json")).json()).flights.length,
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
  assert.equal(await request("data/flights.json"), undefined);
  assert(!fetched.some((url) => url.endsWith("data/flights.json")));
  await storage.open("central-canteen-v1");
  await storage.open("flight-scanner-old");
  const dataCache = await storage.open("flight-scanner-data");
  await dataCache.put("data/flights.json", Response.json(snapshot()));
  let activation;
  handlers.activate({ waitUntil: (p) => (activation = p) });
  await activation;
  assert(stores.has("central-canteen-v1"));
  assert(!stores.has("flight-scanner-old"));
  assert(stores.has("flight-scanner-data"));
  assert.equal(await dataCache.match("data/flights.json"), undefined);
});

test("calendar groups all quotes by day and uses round-trip minima beyond the first page", async (t) => {
  const data = snapshot();
  data.flights[120].price = 5;
  const app = start(data);
  t.after(app.close);
  const { d, count } = app;
  await until(() => count() === 137);
  assert(d.getElementById("calendar").hidden);
  d.querySelector('[data-layout="calendar"]').click();
  assert(!d.getElementById("calendar").hidden);
  const outbound = d.querySelector('[data-kind="outbound"][data-date="2030-01-01"]');
  assert.equal(outbound.querySelector("small").textContent, "€5");
  assert(outbound.classList.contains("lowest-fare"));
  assert.equal(d.querySelectorAll('[data-kind="outbound"]').length, 31);
  outbound.click();
  assert.equal(count(), 7);
  assert.equal(d.getElementById("outbound-date").value, "2030-01-01");
  assert.equal(d.querySelector('[data-kind="return"][data-date="2030-01-28"] small').textContent, "€5");
  assert.equal(d.querySelector('[data-kind="outbound"][data-date="2030-01-01"]').getAttribute("aria-pressed"), "true");
  d.querySelector('[data-layout="list"]').click();
  assert(d.getElementById("calendar").hidden);
  assert.equal(count(), 7);
  d.getElementById("clear-dates").click();
  assert.equal(count(), 137);
  assert.match(d.getElementById("result-count").textContent, /137 matching/);
});

test("selecting outbound and return dates shows only that pair and supports empty dates", async (t) => {
  const data = snapshot(4);
  const dates = [
    ["2030-01-01", "2030-01-08", 100],
    ["2030-01-01", "2030-01-09", 60],
    ["2030-01-02", "2030-01-08", 80],
    ["2030-01-02", "2030-02-03", 40],
  ];
  data.flights.forEach((f, i) => {
    f.departure_at = `${dates[i][0]}T08:35`;
    f.return_at = `${dates[i][1]}T18:00`;
    f.price = dates[i][2];
  });
  const app = start(data);
  t.after(app.close);
  const { d, change, count } = app;
  await until(() => count() === 4);
  d.querySelector('[data-layout="calendar"]').click();
  d.querySelector('[data-kind="outbound"][data-date="2030-01-01"]').click();
  assert.equal(count(), 2);
  assert.equal(d.querySelector('[data-kind="return"][data-date="2030-01-08"] small').textContent, "€100");
  assert.equal(d.querySelector('[data-kind="return"][data-date="2030-01-09"] small').textContent, "€60");
  d.querySelector('[data-kind="return"][data-date="2030-01-09"]').click();
  assert.equal(count(), 1);
  assert.match(d.querySelector(".date-group .price").textContent, /€60/);
  change("return-date", "2030-01-10");
  assert.equal(count(), 0);
  assert.match(d.getElementById("results").textContent, /No matches/);
  // The outbound calendar stays explorable even when the selected pair has no quote.
  assert.equal(d.querySelector('[data-kind="outbound"][data-date="2030-01-02"] small').textContent, "€40");
  change("outbound-date", "2030-01-12");
  assert.equal(d.getElementById("return-date").value, "");
  assert(d.querySelector('[data-kind="return"][data-date="2030-01-11"]').disabled);
  d.getElementById("clear-dates").click();
  assert.equal(count(), 4);
});

test("calendar prices follow airport, direct-flight and budget filters", async (t) => {
  const data = snapshot(4);
  data.flights.forEach((f) => (f.departure_at = "2030-01-01T08:35"));
  data.flights[0].price = 150;
  data.flights[1].price = 20;
  data.flights[2].price = 80;
  data.flights[3].price = 10;
  data.flights[3].in_stops = 1;
  const app = start(data);
  t.after(app.close);
  const { d, w, change, count } = app;
  await until(() => count() === 4);
  d.querySelector('[data-layout="calendar"]').click();
  const price = () => d.querySelector('[data-kind="outbound"][data-date="2030-01-01"] small').textContent;
  assert.equal(price(), "€10");
  d.getElementById("direct-only").checked = true;
  d.getElementById("direct-only").dispatchEvent(new w.Event("change"));
  assert.equal(price(), "€20");
  change("origin", "CPH");
  assert.equal(price(), "€80");
  change("destination", "NAP");
  assert.equal(price(), "€150");
  d.querySelector('[data-view="budget"]').click();
  assert.equal(price(), "—");
  assert.equal(count(), 0);
});

test("calendar month navigation crosses years, and scan changes reset dates", async (t) => {
  const data = snapshot(2);
  data.search.departure_from = "2029-12-01";
  data.search.departure_to = "2030-01-31";
  data.flights[0].departure_at = "2029-12-31T08:35";
  const app = start(data);
  t.after(app.close);
  const { d, state, change, count } = app;
  await until(() => count() === 2 && d.querySelectorAll("#scan option").length === 2);
  d.querySelector('[data-layout="calendar"]').click();
  assert.match(d.querySelector(".month-heading h4").textContent, /December 2029/);
  assert(d.querySelector('[data-month="outbound"][data-step="-1"]').disabled);
  d.querySelector('[data-month="outbound"][data-step="1"]').click();
  assert.match(d.querySelector(".month-heading h4").textContent, /January 2030/);
  assert(d.querySelector('[data-month="outbound"][data-step="1"]').disabled);
  change("outbound-date", "2030-01-02");
  assert.equal(count(), 1);
  d.getElementById("refresh").click();
  await until(() => !d.getElementById("refresh").disabled);
  assert.equal(d.getElementById("outbound-date").value, "2030-01-02");
  change("scan", HISTORY_FILE);
  await until(() => d.getElementById("result-count").textContent.includes("53 matching"));
  assert.equal(d.getElementById("outbound-date").value, "");
  assert.equal(d.getElementById("return-date").value, "");
  assert.match(d.querySelector(".month-heading h4").textContent, /January 2030/);
  state.fail = true;
  d.getElementById("refresh").click();
  await until(() => !d.getElementById("refresh").disabled);
  assert(!d.getElementById("calendar").hidden);
});

test("clicking a selected calendar day clears only that date and updates fares and results", async (t) => {
  const data = snapshot(4);
  data.flights.forEach((f, i) => {
    f.departure_at = `2030-01-0${1 + (i % 2)}T08:35`;
    f.return_at = `2030-01-0${i < 2 ? 8 : 9}T18:00`;
    if (i === 3) f.price = 10;
  });
  const app = start(data);
  t.after(app.close);
  const { d, count } = app;
  await until(() => count() === 4);
  d.querySelector('[data-layout="calendar"]').click();
  const outbound = () => d.querySelector('[data-kind="outbound"][data-date="2030-01-01"]');
  const back = () => d.querySelector('[data-kind="return"][data-date="2030-01-08"]');
  const otherReturnPrice = () => d.querySelector('[data-kind="return"][data-date="2030-01-09"] small').textContent;

  outbound().click();
  back().click();
  assert.equal(count(), 1);
  assert.equal(otherReturnPrice(), "€42");

  outbound().click();
  assert.equal(d.getElementById("outbound-date").value, "");
  assert.equal(d.getElementById("return-date").value, "2030-01-08");
  assert.equal(outbound().getAttribute("aria-pressed"), "false");
  assert.equal(back().getAttribute("aria-pressed"), "true");
  assert.equal(d.getElementById("return-date").min, "");
  assert.equal(d.activeElement, outbound());
  assert.equal(otherReturnPrice(), "€10");
  assert.equal(count(), 2);

  outbound().click();
  back().click();
  assert.equal(d.getElementById("outbound-date").value, "2030-01-01");
  assert.equal(d.getElementById("return-date").value, "");
  assert.equal(outbound().getAttribute("aria-pressed"), "true");
  assert.equal(back().getAttribute("aria-pressed"), "false");
  assert.equal(count(), 2);

  outbound().click();
  assert.equal(count(), 4);
  assert(d.getElementById("clear-dates").disabled);
});

test("one entry per date pair exposes every matching offer, including different hours and routes", async (t) => {
  const data = snapshot(83);
  data.flights.forEach((f, i) => {
    f.departure_at = `2030-01-13T${i % 2 ? '19:45' : '08:35'}`;
    f.return_at = '2030-01-21T18:00';
  });
  data.flights[80].price = 5;
  data.flights.push({ ...data.flights[0], departure_at: '2030-01-14T08:35', price: 20 });
  const app = start(data);
  t.after(app.close);
  const { d, change, count } = app;
  await until(() => count() === 84);
  assert.equal(d.querySelectorAll('.date-group').length, 2);
  assert.match(d.querySelector('.date-group .price').textContent, /€5/);
  assert.match(d.querySelector('.date-group').textContent, /83 offers/);
  assert.equal(d.querySelectorAll('.ticket').length, 0);
  d.querySelector('.date-group .price').click();
  assert(d.getElementById('offers-dialog').open);
  assert.match(d.getElementById('offers-title').textContent, /13 Jan 2030 → 21 Jan 2030/);
  assert.equal(d.querySelectorAll('#offers-results .ticket').length, 40);
  assert.match(d.querySelector('#offers-results .ticket .price').textContent, /€5/);
  assert.match(d.getElementById('offers-results').textContent, /19:45/);
  assert.match(d.getElementById('offers-results').textContent, /08:35/);
  assert(d.querySelector('#offers-results a[href^="https:"]'));
  d.getElementById('offers-next').click();
  assert.equal(d.querySelectorAll('#offers-results .ticket').length, 40);
  d.getElementById('offers-next').click();
  assert.equal(d.querySelectorAll('#offers-results .ticket').length, 3);
  assert(d.getElementById('offers-next').disabled);
  d.getElementById('offers-previous').click();
  assert.match(d.getElementById('offers-page-status').textContent, /Page 2 of 3/);
  d.getElementById('offers-close').click();
  assert(!d.getElementById('offers-dialog').open);
  d.querySelector('.date-group').click();
  assert.match(d.getElementById('offers-page-status').textContent, /Page 1 of 3/);
  change('origin', 'MMX');
  assert(!d.getElementById('offers-dialog').open);
  assert.equal(d.querySelectorAll('.date-group').length, 1);
  assert.match(d.querySelector('.date-group .price').textContent, /€41/);
  d.querySelector('.date-group').click();
  assert.match(d.getElementById('offers-count').textContent, /41 matching offers/);
  assert(!d.getElementById('offers-results').textContent.includes('CPH'));
  assert.equal(data.flights.length, 84);
});

test("compact scans load details only on demand, preserve counts, release memory and allow retry", async (t) => {
  const full = snapshot(3);
  full.flights[1] = { ...full.flights[0], price: 50, departure_at: '2030-01-01T19:45' };
  const file = 'scans/0123456789abcdef01234567/2030-01-01_2030-01-28/0.json.gz';
  const data = { ...full, browser_version: 1, total_count: 3,
    flights: [{ ...full.flights[0], offer_count: 2 }, { ...full.flights[2], offer_count: 1 }],
    detail_files: { '2030-01-01_2030-01-28': [file] } };
  const app = start(data);
  t.after(app.close);
  const { d, state, count } = app;
  state.details.set(`data/browser/${file}`, full.flights.slice(0, 2));
  await until(() => count() === 3);
  assert.equal(d.querySelectorAll('.date-group').length, 2);
  assert.match(d.querySelector('.date-group').textContent, /2 offers/);
  assert(!state.requests.some((url) => url.includes('/scans/')));
  d.querySelector('.date-group').click();
  await until(() => d.querySelectorAll('.ticket').length === 2);
  assert.match(d.getElementById('offers-results').textContent, /19:45/);
  d.getElementById('offers-close').click();
  assert.equal(d.querySelectorAll('.ticket').length, 0);
  state.fail = true;
  d.querySelector('.date-group').click();
  await until(() => d.getElementById('offers-count').textContent.includes('Couldn’t load'));
  assert.equal(d.querySelectorAll('.ticket').length, 0);
  d.getElementById('offers-close').click();
  state.fail = false;
  let resume;
  state.detailsWait = new Promise(resolve => { resume = resolve; });
  d.querySelector('.date-group').click();
  d.getElementById('offers-close').click();
  resume();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(d.querySelectorAll('.ticket').length, 0);
  state.detailsWait = null;
  d.querySelector('.date-group').click();
  await until(() => d.querySelectorAll('.ticket').length === 2);
  assert.equal(count(), 3);
});

function weekendData() {
  const data = snapshot(7);
  const rows = [
    ['2030-01-04', '2030-01-04', '2030-01-13', 110],
    ['2030-01-03', '2030-01-03', '2030-01-13', 30],
    ['2030-01-05', '2030-01-05', '2030-01-13', 10],
    ['2030-01-11', '2030-01-11', '2030-01-20', 70],
    ['2030-01-04', '2030-01-04', '2030-01-06', 1],
    ['2020-01-03', '2020-01-03', '2020-01-12', 1],
    ['2030-01-03', '2030-01-04', '2030-01-13', 80],
  ];
  data.flights.forEach((f, i) => Object.assign(f, {
    origin: i === 3 ? 'MMX' : 'CPH', destination: 'FCO', return_origin: 'FCO', return_destination: 'CPH',
    departure_at: `${rows[i][0]}T18:00`, arrival_out: `${rows[i][1]}T23:00`,
    return_at: `${rows[i][2]}T12:00`, price: rows[i][3],
  }));
  return data;
}

test('weekend accounting handles travel switches, boundaries, Sunday and consecutive weekends', async t => {
  async function trip(from,to) {
    const data=snapshot(1);
    data.flights[0].departure_at=from+'T18:00';
    data.flights[0].return_at=to+'T08:00';
    const app=start(data);
    t.after(app.close);
    await until(()=>app.count()===1);
    app.change('search-mode','double-weekend');
    return app;
  }
  for (const [from,to] of [['2030-01-04','2030-01-13'],['2029-12-28','2030-01-06'],['2032-02-27','2032-03-07'],['2027-03-26','2027-04-04']]) {
    const app=await trip(from,to);
    assert.equal(app.count(),1);
    assert.match(app.d.querySelector('.weekend-score').textContent,/6 weekend days · 4 weekdays/);
  }
  assert.equal((await trip('2030-01-04','2030-01-06')).count(),0);
  assert.equal((await trip('2030-01-04','2030-01-20')).count(),0);
  const app=await trip('2030-01-04','2030-01-13');
  const score=()=>app.d.querySelector('.weekend-score').textContent;
  const check=(id,value)=>{app.d.getElementById(id).checked=value;app.d.getElementById(id).dispatchEvent(new app.w.Event('change'));};
  check('weekend-arrival',false);
  assert.match(score(),/5 weekend days · 4 weekdays/);
  check('weekend-departure',false);
  assert.match(score(),/4 weekend days · 4 weekdays/);
  app.change('weekend-start','6');
  assert.match(score(),/3 weekend days · 6 weekdays/);
  check('weekend-arrival',true);
  check('weekend-departure',true);
  app.change('weekend-start','0');
  assert.match(score(),/2 weekend days · 8 weekdays/);
  check('weekend-departure',false);
  assert.equal(app.count(),0);
});

test('double weekend ranks balance before price, uses destination arrival and preserves filters and details', async t => {
  const app = start(weekendData());
  t.after(app.close);
  const { d, change, count } = app;
  await until(() => count() === 7);
  change('sort','date');
  change('search-mode','double-weekend');
  assert.equal(count(),5);
  assert.equal(d.querySelectorAll('.date-group').length,4);
  assert(d.getElementById('sort').disabled);
  assert.equal(d.getElementById('sort').value,'weekend');
  assert.match(d.querySelector('.date-group').textContent,/6 weekend days · 4 weekdays/);
  assert.match(d.querySelector('.date-group .price').textContent,/€70/);
  const overnight = d.querySelectorAll('.date-group')[1];
  assert.match(overnight.textContent,/€80/); // €30 arrives a day earlier and costs an extra weekday.
  overnight.click();
  assert.match(d.querySelector('.ticket .price').textContent,/€80/);
  assert.match(d.querySelectorAll('.ticket')[1].textContent,/€30/);
  assert.match(d.querySelectorAll('.ticket')[1].textContent,/6 weekend days · 5 weekdays/);
  d.getElementById('offers-close').click();
  change('origin','CPH');
  assert.equal(count(),4);
  d.querySelector('[data-view="budget"]').click();
  assert.equal(count(),3);
  change('outbound-date','2030-01-03');
  assert.equal(count(),2);
  change('search-mode','all');
  assert(!d.getElementById('sort').disabled);
  assert.equal(d.getElementById('sort').value,'date');
  assert.match(d.querySelector('.date-group .price').textContent,/€30/);
});

test('weekend preferences persist and old compact indexes request an online refresh', async t => {
  const prefs = { mode:'double-weekend',start:'6',arrival:false,departure:true };
  const app = start(weekendData(),prefs);
  t.after(app.close);
  await until(() => app.count() === 5);
  assert(!app.d.getElementById('weekend-settings').hidden);
  assert.equal(app.d.getElementById('weekend-start').value,'6');
  assert(!app.d.getElementById('weekend-arrival').checked);
  app.change('weekend-start','5');
  assert.equal(JSON.parse(app.w.localStorage.getItem('flight-scanner-weekends')).start,'5');
  const full = weekendData();
  const file = 'scans/0123456789abcdef01234567/2030-01-03_2030-01-13/0.json.gz';
  const old = { ...full, browser_version:1,total_count:2,
    flights: [full.flights[1],full.flights[6]].map(f=>({...f,offer_count:1})),
    detail_files:{'2030-01-03_2030-01-13':[file]} };
  app.state.data = old;
  app.d.getElementById('refresh').click();
  await until(()=>!app.d.getElementById('refresh').disabled);
  assert.equal(app.count(),0);
  assert.match(app.d.getElementById('notice').textContent,/Refresh while online/);
  app.state.data = {...old,weekend_version:1};
  app.state.details.set(`data/browser/${file}`,[full.flights[1],full.flights[6]]);
  app.d.getElementById('weekend-arrival').checked=true;
  app.d.getElementById('refresh').click();
  await until(()=>!app.d.getElementById('refresh').disabled);
  assert.equal(app.count(),2);
  assert.match(app.d.querySelector('.date-group .price').textContent,/€80/);
  app.d.querySelector('.date-group').click();
  await until(()=>app.d.querySelectorAll('.ticket').length===2);
  assert.match(app.d.querySelector('.ticket .price').textContent,/€80/);
});
