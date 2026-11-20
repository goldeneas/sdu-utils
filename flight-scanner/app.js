"use strict";

const AIRPORTS = {
  BLL: "Billund",
  CPH: "Copenhagen",
  MMX: "Malmö",
  NAP: "Naples",
  QSR: "Salerno",
  FCO: "Rome Fiumicino",
  CIA: "Rome Ciampino",
  MXP: "Milan Malpensa",
  BGY: "Bergamo",
  LIN: "Milan Linate",
  TRN: "Turin",
  BLQ: "Bologna",
  PSA: "Pisa",
};
const SOURCES = {
  travelpayouts: "Aviasales · cached fare",
  ryanair: "Ryanair",
  google: "Google Flights",
  misto: "Mixed sources",
};
const $ = (id) => document.getElementById(id);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let snapshot = null;
let view = "all";
let page = 1;
const PAGE_SIZE = 40;
let loadSequence = 0;
let selectedScan = "";
let loadFailed = false;
let layout = "list";
const calendarMonths = { outbound: "", return: "" };
const calendarRanges = { outbound: null, return: null };
let dateGroups = [];
let selectedGroup = null;
let offerPage = 1;

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
// Flight times are local to each airport. Do not shift them to the viewer's timezone.
function day(value) {
  const [y, m, d] = String(value).slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
  });
}
function clock(value) {
  return value ? String(value).slice(11, 16) : "";
}
function money(value, currency = snapshot?.search.currency || "EUR") {
  try {
    return new Intl.NumberFormat("en-IE", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
      minimumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${value} ${currency}`;
  }
}
function duration(minutes) {
  return Number.isFinite(minutes)
    ? `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`
    : "";
}
function safeLink(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}
function link(value, label) {
  const href = safeLink(value);
  return href
    ? `<a href="${escapeHTML(href)}" target="_blank" rel="noopener noreferrer">${label} <span aria-hidden="true">↗</span></a>`
    : "";
}
function validFlight(f) {
  return (
    f &&
    Number.isFinite(f.price) &&
    f.price >= 0 &&
    typeof f.origin === "string" &&
    typeof f.destination === "string" &&
    /^\d{4}-\d{2}-\d{2}T/.test(f.departure_at) &&
    /^\d{4}-\d{2}-\d{2}T/.test(f.return_at)
  );
}
function validSnapshot(data) {
  return (
    data?.schema_version === 1 &&
    ["ok", "partial", "stale", "unavailable"].includes(data.status) &&
    Array.isArray(data.top) &&
    data.top.every(validFlight) &&
    (data.flights === undefined ||
      (Array.isArray(data.flights) && data.flights.every(validFlight))) &&
    data.per_airport &&
    Object.values(data.per_airport).every(
      (rows) => Array.isArray(rows) && rows.every(validFlight),
    ) &&
    Array.isArray(data.search?.origins) &&
    Array.isArray(data.search?.destinations) &&
    Number.isFinite(data.search.max_price)
  );
}
function leg(f, back = false) {
  const dep = back ? f.return_at : f.departure_at;
  const arrival = back ? f.arrival_back : f.arrival_out;
  const stops = back ? f.in_stops : f.out_stops;
  const from = back ? f.return_origin || f.destination : f.origin;
  const to = back ? f.return_destination || f.origin : f.destination;
  const details = [
    clock(dep) +
      (arrival
        ? ` – ${clock(arrival)}${arrival.slice(0, 10) > dep.slice(0, 10) ? " (+1 day)" : ""}`
        : ""),
    stops === 0 ? "Direct" : `${stops} stop${stops === 1 ? "" : "s"}`,
    duration(back ? f.in_duration_min : f.out_duration_min),
  ];
  const price = back ? f.price_back : f.price_out;
  if (price != null) details.push(money(price, f.currency));
  return `<div class="leg"><span class="leg-label">${back ? "Return" : "Out"}</span><div><div class="leg-line"><span class="leg-route">${escapeHTML(from)}<span aria-hidden="true">→</span><span class="sr-only">to</span>${escapeHTML(to)}</span><span class="leg-day">${escapeHTML(day(dep))}</span></div><p class="leg-detail">${details.filter(Boolean).map(escapeHTML).join(" · ")}</p></div></div>`;
}
function ticket(f, index) {
  const above = f.price > snapshot.search.max_price;
  const separate = Boolean(safeLink(f.return_link));
  const booking = separate
    ? link(f.link, "Outbound") + link(f.return_link, "Return")
    : link(f.link, "Check flight");
  return `<article class="ticket"><div class="ticket-head"><div><p class="ticket-label">${index === 0 && $("sort").value === "price" ? "Best in this view" : `${escapeHTML(f.nights)} nights away`}</p><h3 class="destination-name">${escapeHTML(AIRPORTS[f.destination] || f.destination)}</h3><p class="airline">${escapeHTML(f.airline)}</p></div><div class="price"><strong>${escapeHTML(money(f.price, f.currency))}</strong><small>round trip / person</small></div></div><div class="itinerary">${leg(f)}${leg(f, true)}</div>${f.open_jaw ? '<p class="ticket-warning">Different airports on the return trip. Plan your ground transport.</p>' : ""}${f.departure_at.slice(0, 10) < today() ? '<p class="ticket-warning">Departure has passed · saved for reference.</p>' : ""}<div class="ticket-foot"><div class="ticket-tags"><span>${escapeHTML(f.nights)} nights · ${escapeHTML(SOURCES[f.source] || f.source)}</span><span>${separate ? "Two separate tickets" : "Round-trip booking"}${above ? ' · <span class="over-budget">Above deal budget</span>' : ""}</span></div><div class="booking">${booking || '<span class="muted">Link unavailable</span>'}</div></div></article>`;
}
function empty(title, message) {
  return `<div class="empty"><span class="empty-icon" aria-hidden="true">↗</span><h3>${escapeHTML(title)}</h3><p>${escapeHTML(message)}</p></div>`;
}
function renderNotice() {
  const notes = [];
  if (!navigator.onLine)
    notes.push("You’re offline. Showing the last downloaded results.");
  else if (loadFailed && snapshot)
    notes.push("Couldn’t refresh. Showing your last loaded results.");
  if (snapshot) {
    if (!Array.isArray(snapshot.flights))
      notes.push(
        "This older scan contains only saved highlights. Full results are kept from the next successful scan onward.",
      );
    if (snapshot.status === "unavailable")
      notes.push(
        "The scanner couldn’t collect flight data. It will try again on the next daily run.",
      );
    else if (snapshot.status === "stale")
      notes.push(
        "The latest scan couldn’t be completed. These are the last available results.",
      );
    else if (
      snapshot.generated_at &&
      Date.now() - Date.parse(snapshot.generated_at) > 36 * 3600000
    )
      notes.push(
        "These results are more than a day old. Check the current fare before booking.",
      );
    if (snapshot.status === "partial")
      notes.push(
        "Some sources were unavailable. These are the flights the available sources found.",
      );
  }
  $("notice").textContent = notes.join(" ");
  $("notice").hidden = !notes.length;
}
function allFlights(data) {
  if (Array.isArray(data.flights)) return data.flights;
  const seen = new Set();
  return [...data.top, ...Object.values(data.per_airport).flat()].filter(
    (f) => {
      const key = JSON.stringify([
        f.origin,
        f.destination,
        f.return_origin,
        f.return_destination,
        f.departure_at,
        f.return_at,
        f.airline,
        f.price,
      ]);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    },
  );
}
function dateKey(value) {
  return String(value).slice(0, 10);
}
function groupDates(flights) {
  const groups = new Map();
  for (const f of flights) {
    const key = `${dateKey(f.departure_at)}/${dateKey(f.return_at)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(f);
  }
  return [...groups.values()].map((offers) => offers.sort((a, b) =>
    a.price - b.price || a.departure_at.localeCompare(b.departure_at) || a.return_at.localeCompare(b.return_at),
  ));
}
function pairLabel(f) {
  return `${day(f.departure_at)} ${f.departure_at.slice(0, 4)} → ${day(f.return_at)} ${f.return_at.slice(0, 4)}`;
}
function dateGroup(offers, index) {
  const f = offers[0];
  return `<button type="button" class="date-group" data-group="${index}" aria-haspopup="dialog"><span class="ticket-head"><span><span class="ticket-label">${escapeHTML(pairLabel(f))}</span><span class="destination-name">${escapeHTML(AIRPORTS[f.destination] || f.destination)}</span><span class="airline">${escapeHTML(`${f.origin} → ${f.destination} · ${f.airline}`)}</span></span><span class="price"><small>From</small><strong>${escapeHTML(money(f.price, f.currency))}</strong><small>round trip / person</small></span></span><span class="group-foot"><span>${offers.length.toLocaleString()} offer${offers.length === 1 ? "" : "s"} · ${escapeHTML(f.nights)} nights${dateKey(f.departure_at) < today() ? " · Departure has passed" : ""}</span><span>View offers <span aria-hidden="true">↗</span></span></span></button>`;
}
function renderOffers() {
  if (!selectedGroup) return;
  const pages = Math.max(1, Math.ceil(selectedGroup.length / PAGE_SIZE));
  offerPage = Math.min(Math.max(1, offerPage), pages);
  const start = (offerPage - 1) * PAGE_SIZE;
  $("offers-title").textContent = pairLabel(selectedGroup[0]);
  $("offers-count").textContent = `${selectedGroup.length.toLocaleString()} matching offers · Lowest price first · Current filters apply`;
  $("offers-results").innerHTML = selectedGroup.slice(start, start + PAGE_SIZE)
    .map((f, i) => ticket(f, start + i)).join("");
  $("offers-pagination").hidden = pages <= 1;
  $("offers-previous").disabled = offerPage === 1;
  $("offers-next").disabled = offerPage === pages;
  $("offers-page-status").textContent = `Page ${offerPage} of ${pages.toLocaleString()}`;
}
function monthOffset(month, offset) {
  const [year, number] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, number - 1 + offset, 1));
  return date.toISOString().slice(0, 7);
}
function calendarBounds(kind) {
  if (calendarRanges[kind]) return calendarRanges[kind];
  let first = "", last = "";
  for (const f of allFlights(snapshot)) {
    const month = (kind === "outbound" ? f.departure_at : f.return_at).slice(0, 7);
    if (!first || month < first) first = month;
    if (!last || month > last) last = month;
  }
  if (kind === "outbound" || !first) {
    const from = snapshot.search.departure_from.slice(0, 7);
    const to = snapshot.search.departure_to.slice(0, 7);
    if (!first || from < first) first = from;
    if (!last || to > last) last = to;
  }
  return (calendarRanges[kind] = [first, last]);
}
function renderCalendars(flights) {
  $("calendar").hidden = layout !== "calendar";
  $("clear-dates").disabled = !$("outbound-date").value && !$("return-date").value;
  $("return-date").min = $("outbound-date").value;
  if (layout !== "calendar") return;
  $("calendar-explainer").textContent =
    "Each day shows the lowest round-trip price per person from this scan. " +
    ($("outbound-date").value
      ? `Return fares are for departure on ${day($("outbound-date").value)} ${$("outbound-date").value.slice(0, 4)}.`
      : "Choose an outbound day to compare return fares.");
  $("calendar-months").innerHTML = ["outbound", "return"].map((kind) => {
    const bounds = calendarBounds(kind);
    const month = calendarMonths[kind] || bounds[0];
    calendarMonths[kind] = month;
    const [year, number] = month.split("-").map(Number);
    const monthName = new Date(Date.UTC(year, number - 1, 1)).toLocaleDateString("en-GB", {
      month: "long", year: "numeric", timeZone: "UTC",
    });
    const prices = new Map();
    for (const f of flights) {
      if (kind === "return" && $("outbound-date").value &&
          dateKey(f.departure_at) !== $("outbound-date").value) continue;
      const key = dateKey(kind === "outbound" ? f.departure_at : f.return_at);
      prices.set(key, Math.min(prices.get(key) ?? Infinity, f.price));
    }
    const monthPrices = [...prices].filter(([key]) => key.startsWith(month)).map(([, price]) => price);
    const lowest = Math.min(...monthPrices);
    const offset = (new Date(Date.UTC(year, number - 1, 1)).getUTCDay() + 6) % 7;
    const days = new Date(Date.UTC(year, number, 0)).getUTCDate();
    const label = kind === "outbound" ? "Outbound" : "Return";
    let cells = '<span class="calendar-blank" aria-hidden="true"></span>'.repeat(offset);
    for (let n = 1; n <= days; n++) {
      const key = `${month}-${String(n).padStart(2, "0")}`;
      const price = prices.get(key);
      const selected = $(`${kind}-date`).value === key;
      const disabled = kind === "return" && $("outbound-date").value && key < $("outbound-date").value;
      const fullDate = new Date(`${key}T12:00:00Z`).toLocaleDateString("en-GB", {
        day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
      });
      cells += `<button type="button" class="calendar-day${price === lowest ? " lowest-fare" : ""}" data-date="${key}" data-kind="${kind}" aria-pressed="${selected}" aria-label="${escapeHTML(`${label} ${fullDate}, ${price === undefined ? "no saved fare" : `round trip from ${money(price)}`}`)}" ${disabled ? "disabled" : ""}><span>${n}</span><small>${price === undefined ? "—" : escapeHTML(money(price))}</small></button>`;
    }
    return `<div class="calendar-month"><p class="calendar-leg">${label}${kind === "return" && $("outbound-date").value ? ` · from ${escapeHTML(day($("outbound-date").value))}` : " · any dates"}</p><div class="month-heading"><button type="button" class="quiet" data-month="${kind}" data-step="-1" aria-label="Previous ${kind} month" ${month <= bounds[0] ? "disabled" : ""}>←</button><h4>${escapeHTML(monthName)}</h4><button type="button" class="quiet" data-month="${kind}" data-step="1" aria-label="Next ${kind} month" ${month >= bounds[1] ? "disabled" : ""}>→</button></div><div class="calendar-grid"><div class="weekdays" aria-hidden="true">${["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => `<span>${d}</span>`).join("")}</div>${cells}</div></div>`;
  }).join("");
}
function datesChanged(kind) {
  const value = $(`${kind}-date`).value;
  if (value) calendarMonths[kind] = value.slice(0, 7);
  if (kind === "outbound" && value) {
    if ($("return-date").value && $("return-date").value < value)
      $("return-date").value = "";
    if (!$("return-date").value) calendarMonths.return = value.slice(0, 7);
  }
  page = 1;
  render();
}
function render() {
  renderNotice();
  if (!snapshot) return;
  if ($("offers-dialog").open) $("offers-dialog").close();
  selectedGroup = null;
  $("offers-results").replaceChildren();
  const s = snapshot.search;
  const raw = allFlights(snapshot);
  const filtered = raw.filter(
    (f) =>
      (!$("origin").value || f.origin === $("origin").value) &&
      (!$("destination").value || f.destination === $("destination").value) &&
      (!$("return-origin").value ||
        (f.return_origin || f.destination) === $("return-origin").value) &&
      (!$("return-destination").value ||
        (f.return_destination || f.origin) === $("return-destination").value) &&
      (!$("direct-only").checked || (f.out_stops === 0 && f.in_stops === 0)) &&
      (view !== "budget" || f.price <= s.max_price),
  );
  renderCalendars(filtered);
  const flights = filtered.filter((f) =>
    (!$("outbound-date").value || dateKey(f.departure_at) === $("outbound-date").value) &&
    (!$("return-date").value || dateKey(f.return_at) === $("return-date").value),
  );
  dateGroups = groupDates(flights);
  dateGroups.sort(
    $("sort").value === "date"
      ? (a, b) =>
          dateKey(a[0].departure_at).localeCompare(dateKey(b[0].departure_at)) ||
          dateKey(a[0].return_at).localeCompare(dateKey(b[0].return_at)) || a[0].price - b[0].price
      : (a, b) =>
          a[0].price - b[0].price || a[0].departure_at.localeCompare(b[0].departure_at),
  );
  const pages = Math.max(1, Math.ceil(dateGroups.length / PAGE_SIZE));
  page = Math.min(Math.max(1, page), pages);
  const start = (page - 1) * PAGE_SIZE;
  $("result-count").textContent = flights.length
    ? `Showing ${start + 1}–${Math.min(start + PAGE_SIZE, dateGroups.length)} of ${dateGroups.length.toLocaleString()} date pairs · ${flights.length.toLocaleString()} matching round trips · ${raw.length.toLocaleString()} saved in this scan${view === "budget" ? ` · Up to ${money(s.max_price)}` : " · All prices"}`
    : `0 matching round trips · ${raw.length.toLocaleString()} saved in this scan`;
  const cheapest = flights.reduce(
    (best, f) => Math.min(best, f.price),
    Infinity,
  );
  $("best").hidden = !flights.length;
  $("best").textContent = flights.length
    ? `Round trips from ${money(cheapest)}`
    : "";
  $("pagination").hidden = pages <= 1;
  $("previous-page").disabled = page === 1;
  $("next-page").disabled = page === pages;
  $("page-status").textContent = `Page ${page} of ${pages.toLocaleString()}`;
  if (flights.length)
    $("results").innerHTML = dateGroups
      .slice(start, start + PAGE_SIZE)
      .map((offers, index) => dateGroup(offers, start + index))
      .join("");
  else if (snapshot.status === "unavailable")
    $("results").innerHTML = empty(
      "The board is waiting for a scan",
      "Flight data is unavailable right now. Come back after the next daily scan.",
    );
  else if (raw.length)
    $("results").innerHTML = empty(
      "No matches for these filters",
      "Try other dates or airports, include connecting flights, or choose All flights to include every price.",
    );
  else
    $("results").innerHTML = empty(
      "No round trips found in this scan",
      "No matching round trips were found within the configured search dates, stay length and stop limit.",
    );
}
function updateFilters(id, codes, fallback) {
  const selected = $(id).value;
  $(id).replaceChildren(
    new Option(fallback, ""),
    ...codes.map(
      (code) => new Option(`${AIRPORTS[code] || code} (${code})`, code),
    ),
  );
  if (codes.includes(selected)) $(id).value = selected;
}
function showSnapshot(data) {
  snapshot = data;
  calendarRanges.outbound = null;
  calendarRanges.return = null;
  const s = data.search;
  $("origin-summary").textContent = s.origins
    .map((code) => AIRPORTS[code] || code)
    .join(" · ");
  $("origin-codes").textContent = s.origins.join(" / ");
  $("search-summary").textContent =
    `${s.min_nights}–${s.max_nights} nights · Deal budget ${money(s.max_price)} · ${s.max_transfers === 0 ? "Direct flights" : `Max. ${s.max_transfers} stop${s.max_transfers === 1 ? "" : "s"} each way`}`;
  $("window").textContent =
    `Departures ${day(s.departure_from)} – ${day(s.departure_to)} ${s.departure_to.slice(0, 4)}`;
  $("updated").textContent = data.generated_at
    ? `Scan ${new Date(data.generated_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short" })} · All flight times local`
    : "No successful scan published yet";
  const flights = allFlights(data);
  updateFilters(
    "origin",
    [...new Set([...s.origins, ...flights.map((f) => f.origin)])],
    "All airports",
  );
  updateFilters(
    "destination",
    [...new Set([...s.destinations, ...flights.map((f) => f.destination)])],
    "All airports",
  );
  updateFilters(
    "return-origin",
    [
      ...new Set([
        ...s.destinations,
        ...flights.map((f) => f.return_origin || f.destination),
      ]),
    ],
    "All airports",
  );
  updateFilters(
    "return-destination",
    [
      ...new Set([
        ...s.origins,
        ...flights.map((f) => f.return_destination || f.origin),
      ]),
    ],
    "All airports",
  );
  page = 1;
  render();
}
function safeHistoryFile(file) {
  return (
    typeof file === "string" && /^scans\/[A-Za-z0-9_-]+\.json\.gz$/.test(file)
  );
}
async function loadHistory() {
  try {
    const response = await fetch("data/history/index.json", {
      cache: "no-cache",
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) throw new Error("History unavailable");
    const data = await response.json();
    if (
      data.schema_version !== 1 ||
      !Array.isArray(data.scans) ||
      !data.scans.every(
        (scan) =>
          safeHistoryFile(scan.file) &&
          Number.isFinite(scan.count) &&
          Number.isFinite(Date.parse(scan.generated_at)),
      )
    )
      throw new Error("Invalid history");
    const selected = $("scan").value;
    $("scan").replaceChildren(
      new Option("Latest published scan", ""),
      ...data.scans.map(
        (scan) =>
          new Option(
            `${new Date(scan.generated_at).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })} · ${scan.count.toLocaleString()} round trips${scan.complete_results ? "" : " · highlights"}`,
            scan.file,
          ),
      ),
    );
    if (data.scans.some((scan) => scan.file === selected))
      $("scan").value = selected;
    $("history-status").textContent =
      `${data.scans.length} saved scan${data.scans.length === 1 ? "" : "s"}`;
  } catch {
    $("history-status").textContent =
      "History unavailable; latest results are still accessible.";
  }
}
async function load() {
  const sequence = ++loadSequence;
  const scan = $("scan").value;
  if (scan && !safeHistoryFile(scan)) return;
  $("refresh").disabled = true;
  $("results").setAttribute("aria-busy", "true");
  try {
    const response = await fetch(
      scan ? `data/history/${scan}` : "data/flights.json",
      { cache: "no-cache", signal: AbortSignal.timeout(60000) },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    let data;
    if (scan) {
      const bytes = new Uint8Array(await response.arrayBuffer());
      // Some hosts decode Content-Encoding before fetch exposes the response body.
      data =
        bytes[0] === 0x1f && bytes[1] === 0x8b
          ? await new Response(
              new Blob([bytes])
                .stream()
                .pipeThrough(new DecompressionStream("gzip")),
            ).json()
          : JSON.parse(new TextDecoder().decode(bytes));
    } else data = await response.json();
    if (sequence !== loadSequence) return;
    if (!validSnapshot(data)) throw new Error("Invalid flight snapshot");
    loadFailed = false;
    if (selectedScan !== scan) {
      $("outbound-date").value = "";
      $("return-date").value = "";
      calendarMonths.outbound = "";
      calendarMonths.return = "";
    }
    selectedScan = scan;
    showSnapshot(data);
  } catch {
    if (sequence !== loadSequence) return;
    loadFailed = true;
    $("scan").value = selectedScan;
    if (snapshot) render();
    else {
      $("updated").textContent = "Flight results are unavailable";
      $("results").innerHTML = empty(
        "The departure board isn’t ready yet",
        "The first scan may still be running. Try Refresh again shortly. After your first visit, results are available offline.",
      );
      renderNotice();
    }
  } finally {
    if (sequence === loadSequence) {
      $("refresh").disabled = false;
      $("results").setAttribute("aria-busy", "false");
    }
  }
}
document.querySelectorAll("[data-view]").forEach((button) =>
  button.addEventListener("click", () => {
    view = button.dataset.view;
    page = 1;
    document
      .querySelectorAll("[data-view]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    render();
  }),
);
document.querySelectorAll("[data-layout]").forEach((button) =>
  button.addEventListener("click", () => {
    layout = button.dataset.layout;
    document.querySelectorAll("[data-layout]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b === button)),
    );
    render();
  }),
);
["outbound", "return"].forEach((kind) =>
  $(`${kind}-date`).addEventListener("change", () => datesChanged(kind)),
);
$("clear-dates").addEventListener("click", () => {
  $("outbound-date").value = "";
  $("return-date").value = "";
  page = 1;
  render();
});
$("calendar-months").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  if (button.dataset.date) {
    const input = $(`${button.dataset.kind}-date`);
    input.value = input.value === button.dataset.date ? "" : button.dataset.date;
    datesChanged(button.dataset.kind);
    $("calendar-months").querySelector(`[data-kind="${button.dataset.kind}"][data-date="${button.dataset.date}"]`)?.focus();
  } else if (button.dataset.month) {
    const kind = button.dataset.month;
    calendarMonths[kind] = monthOffset(calendarMonths[kind], Number(button.dataset.step));
    render();
    $("calendar-months").querySelector(`[data-month="${kind}"][data-step="${button.dataset.step}"]`)?.focus();
  }
});
[
  "origin",
  "destination",
  "return-origin",
  "return-destination",
  "direct-only",
  "sort",
].forEach((id) =>
  $(id).addEventListener("change", () => {
    page = 1;
    render();
  }),
);
$("scan").addEventListener("change", load);
$("results").addEventListener("click", (event) => {
  const button = event.target.closest("[data-group]");
  if (!button) return;
  selectedGroup = dateGroups[Number(button.dataset.group)];
  offerPage = 1;
  renderOffers();
  $("offers-dialog").showModal();
});
$("offers-close").addEventListener("click", () => $("offers-dialog").close());
$("offers-previous").addEventListener("click", () => { offerPage--; renderOffers(); });
$("offers-next").addEventListener("click", () => { offerPage++; renderOffers(); });
$("previous-page").addEventListener("click", () => {
  page--;
  render();
});
$("next-page").addEventListener("click", () => {
  page++;
  render();
});
$("refresh").addEventListener("click", () => {
  load();
  loadHistory();
});
window.addEventListener("offline", renderNotice);
window.addEventListener("online", () => {
  load();
  loadHistory();
});
window.addEventListener("pageshow", render);
load();
loadHistory();
