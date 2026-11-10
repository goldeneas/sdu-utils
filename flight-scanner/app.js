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
let view = "top";
let loadFailed = false;

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
    f.price > 0 &&
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
  const from = back ? f.return_origin : f.origin;
  const to = back ? f.return_destination : f.destination;
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
  return `<article class="ticket"><div class="ticket-head"><div><p class="ticket-label">${index === 0 && $("sort").value === "price" ? "Best in this view" : `${escapeHTML(f.nights)} nights away`}</p><h3 class="destination-name">${escapeHTML(AIRPORTS[f.destination] || f.destination)}</h3><p class="airline">${escapeHTML(f.airline)}</p></div><div class="price"><strong>${escapeHTML(money(f.price, f.currency))}</strong><small>round trip / person</small></div></div><div class="itinerary">${leg(f)}${leg(f, true)}</div>${f.open_jaw ? '<p class="ticket-warning">Different airports on the return trip. Plan your ground transport.</p>' : ""}<div class="ticket-foot"><div class="ticket-tags"><span>${escapeHTML(f.nights)} nights · ${escapeHTML(SOURCES[f.source] || f.source)}</span><span>${separate ? "Two separate tickets" : "Round-trip booking"}${above ? ' · <span class="over-budget">Above deal budget</span>' : ""}</span></div><div class="booking">${booking || '<span class="muted">Link unavailable</span>'}</div></div></article>`;
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
function render() {
  renderNotice();
  if (!snapshot) return;
  const s = snapshot.search;
  const raw =
    view === "top" ? snapshot.top : Object.values(snapshot.per_airport).flat();
  const upcoming = raw.filter((f) => f.departure_at.slice(0, 10) >= today());
  const flights = upcoming.filter(
    (f) =>
      (!$("origin").value || f.origin === $("origin").value) &&
      (!$("destination").value || f.destination === $("destination").value),
  );
  flights.sort(
    $("sort").value === "date"
      ? (a, b) =>
          a.departure_at.localeCompare(b.departure_at) || a.price - b.price
      : (a, b) => a.price - b.price,
  );
  $("result-count").textContent =
    view === "top"
      ? `${flights.length} of the top ${s.top_n} finds · Round trips up to ${money(s.max_price)} · Departed flights hidden`
      : `${flights.length} finds · Best per destination, including fares above ${money(s.max_price)} · Departed flights hidden`;
  const cheapest = flights.length
    ? Math.min(...flights.map((f) => f.price))
    : null;
  $("best").hidden = cheapest === null;
  $("best").textContent =
    cheapest === null ? "" : `Round trips from ${money(cheapest)}`;
  if (flights.length) $("results").innerHTML = flights.map(ticket).join("");
  else if (snapshot.status === "unavailable")
    $("results").innerHTML = empty(
      "The board is waiting for a scan",
      "Flight data is unavailable right now. Come back after the next daily scan.",
    );
  else if ($("origin").value || $("destination").value)
    $("results").innerHTML = empty(
      "No matches for these airports",
      "Try all airports, or switch to By destination to see more options.",
    );
  else if (raw.length && !upcoming.length)
    $("results").innerHTML = empty(
      "These flights have already departed",
      "Upcoming results will appear after the next successful daily scan.",
    );
  else
    $("results").innerHTML = empty(
      view === "top"
        ? "No deals within budget this time"
        : "No flights found for these destinations",
      view === "top"
        ? `No round trips up to ${money(s.max_price)} were found. Check By destination for the best fares at any price.`
        : "The next daily scan will check again.",
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
  const s = data.search;
  $("origin-summary").textContent = s.origins
    .map((code) => AIRPORTS[code] || code)
    .join(" · ");
  $("origin-codes").textContent = s.origins.join(" / ");
  $("search-summary").textContent =
    `${s.min_nights}–${s.max_nights} nights · Up to ${money(s.max_price)} round trip · ${s.max_transfers === 0 ? "Direct flights" : `Max. ${s.max_transfers} stop${s.max_transfers === 1 ? "" : "s"} each way`}`;
  $("window").textContent =
    `Departures ${day(s.departure_from)} – ${day(s.departure_to)} ${s.departure_to.slice(0, 4)}`;
  $("updated").textContent = data.generated_at
    ? `Last scan ${new Date(data.generated_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short" })} · All flight times local`
    : "No successful scan published yet";
  updateFilters("origin", s.origins, "All airports");
  updateFilters("destination", s.destinations, "All destinations");
  render();
}
async function load() {
  $("refresh").disabled = true;
  $("results").setAttribute("aria-busy", "true");
  try {
    const response = await fetch("data/flights.json", {
      cache: "no-cache",
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!validSnapshot(data)) throw new Error("Invalid flight snapshot");
    loadFailed = false;
    showSnapshot(data);
  } catch {
    loadFailed = true;
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
    $("refresh").disabled = false;
    $("results").setAttribute("aria-busy", "false");
  }
}
document.querySelectorAll("[data-view]").forEach((button) =>
  button.addEventListener("click", () => {
    view = button.dataset.view;
    document
      .querySelectorAll("[data-view]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    render();
  }),
);
["origin", "destination", "sort"].forEach((id) =>
  $(id).addEventListener("change", render),
);
$("refresh").addEventListener("click", load);
window.addEventListener("offline", renderNotice);
window.addEventListener("online", load);
window.addEventListener("pageshow", render);
load();
