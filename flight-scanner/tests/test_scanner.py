import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.config import AirportsConfig, Config, SearchConfig, SourcesConfig  # noqa: E402
from scanner.models import OneWayFare  # noqa: E402
from scanner.ryanair import parse_fares  # noqa: E402
from scanner.search import combine_one_way, filter_offers, months_in_window, run_search  # noqa: E402
from scanner.travelpayouts import parse_offer  # noqa: E402

TODAY = dt.date(2026, 10, 5)


def item(price, dep="2026-10-12T08:40:00+02:00", ret="2026-10-17T19:00:00+02:00", **kw):
    d = {
        "origin": "CPH", "destination": "NAP", "price": price, "airline": "FR",
        "departure_at": dep, "return_at": ret, "transfers": 0, "return_transfers": 0,
        "duration_to": 175, "duration_back": 180, "link": "/search/CPH1210NAP1710?t=x",
    }
    d.update(kw)
    return d


def cfg(**kw):
    return Config(
        search=SearchConfig(max_price=100, min_nights=3, window_days=30, **kw),
        airports=AirportsConfig(origins=["CPH"], destinations=["NAP"]),
        sources=SourcesConfig(ryanair=False, google_flights=False),
    )


def offers(*items):
    return [parse_offer(i, "CPH", "NAP", "EUR") for i in items]


def test_parse_offer():
    o = parse_offer(item(79), "CPH", "NAP", "EUR")
    assert o.price == 79 and o.nights == 5 and o.departure_at.hour == 8
    assert o.arrival_out.strftime("%H:%M") == "11:35" and o.arrival_back.strftime("%H:%M") == "22:00"
    assert o.link.startswith("https://www.aviasales.com/search/")
    assert parse_offer({"price": 5}, "CPH", "NAP", "EUR") is None


def test_filters():
    c = cfg()
    start, end = TODAY + dt.timedelta(days=1), TODAY + dt.timedelta(days=30)
    got = filter_offers(
        offers(
            item(79),                                                  # ok
            item(79),                                                  # duplicato
            item(150),                                                 # troppo caro
            item(50, ret="2026-10-14T19:00:00+02:00"),                 # solo 2 notti
            item(50, transfers=2),                                     # troppi scali
            item(50, dep="2026-12-01T08:00:00+01:00", ret="2026-12-06T08:00:00+01:00"),  # fuori finestra
            item(100, ret="2026-10-18T19:00:00+02:00"),                                              # = soglia, incluso
        ),
        c, start, end,
    )
    assert [o.price for o in got] == [79.0, 100.0]


def test_return_may_fall_after_window_end():
    c = cfg()
    start, end = TODAY + dt.timedelta(days=1), TODAY + dt.timedelta(days=30)   # fine finestra: 4 nov
    late = item(60, dep="2026-11-04T08:00:00+01:00", ret="2026-11-10T08:00:00+01:00")
    assert len(filter_offers(offers(late), c, start, end)) == 1
    too_late_dep = item(60, dep="2026-11-05T08:00:00+01:00", ret="2026-11-10T08:00:00+01:00")
    assert filter_offers(offers(too_late_dep), c, start, end) == []


def test_months():
    assert months_in_window(dt.date(2026, 10, 6), dt.date(2026, 11, 4)) == ["2026-10", "2026-11"]
    assert months_in_window(dt.date(2026, 12, 20), dt.date(2027, 1, 19)) == ["2026-12", "2027-01"]


class FakeClient:
    def __init__(self):
        self.calls = []

    def search_month(self, o, d, m):
        self.calls.append((o, d, m))
        return offers(item(60)) if m == "2026-10" else []


def test_run_search():
    c = cfg(request_delay_seconds=0)
    fc = FakeClient()
    top = run_search(c, client=fc, today=TODAY)
    assert len(fc.calls) == 2 and len(top) == 1 and top[0].price == 60


def fare(o, d, day, price):
    return OneWayFare(o, d, dt.datetime.fromisoformat(f"{day}T07:00:00"), price, "Ryanair", f"https://r/originIata={o}")


def test_parse_ryanair():
    payload = {"outbound": {"fares": [
        {"departureDate": "2026-10-12T06:30:00", "arrivalDate": "2026-10-12T09:15:00",
         "price": {"value": 19.99}, "soldOut": False},
        {"departureDate": "2026-10-13T06:30:00", "price": {"value": 9.99}, "soldOut": True},
        {"departureDate": "2026-10-14T06:30:00", "price": None},
    ]}}
    got = parse_fares(payload, "CPH", "FCO", "EUR")
    assert got[0].arrival_at.hour == 9
    assert len(got) == 1 and got[0].price == 19.99 and "originIata=CPH" in got[0].link


def test_open_jaw_combination():
    fares = [
        fare("CPH", "FCO", "2026-10-12", 20),
        fare("FCO", "CPH", "2026-10-17", 70),   # stessa rotta: 90
        fare("MXP", "CPH", "2026-10-17", 25),   # open-jaw: 45
        fare("MXP", "CPH", "2026-10-14", 5),    # solo 2 notti: scartata
        fare("BLL", "FCO", "2026-10-12", 95),   # tratta troppo cara in combinazione
    ]
    args = (["CPH", "BLL"], ["FCO", "MXP"], 100, 3)
    got = combine_one_way(fares, *args, open_jaw=True)
    assert sorted(o.price for o in got) == [45, 90]
    jaw = next(o for o in got if o.price == 45)
    assert jaw.open_jaw and jaw.return_origin == "MXP"
    same = combine_one_way(fares, *args, open_jaw=False)
    assert [o.price for o in same] == [90] and not same[0].open_jaw


class FakeRyanair:
    def search_month(self, o, d, m):
        if m != "2026-10":
            return []
        return {
            ("CPH", "FCO"): [fare("CPH", "FCO", "2026-10-12", 20)],
            ("MXP", "CPH"): [fare("MXP", "CPH", "2026-10-17", 25)],
        }.get((o, d), [])


def test_run_search_with_ryanair(capsys):
    c = Config(
        search=SearchConfig(max_price=100, min_nights=3, window_days=30, request_delay_seconds=0),
        airports=AirportsConfig(origins=["CPH"], destinations=["FCO", "MXP"]),
        sources=SourcesConfig(travelpayouts=False, ryanair=True, google_flights=False, open_jaw=True),
    )
    top = run_search(c, ryanair=FakeRyanair(), today=TODAY)
    assert [o.price for o in top] == [45] and top[0].open_jaw
    assert "aeroporti diversi" in capsys.readouterr().out


def test_max_nights():
    fares = [
        fare("CPH", "FCO", "2026-10-12", 20),
        fare("FCO", "CPH", "2026-10-20", 30),   # 8 notti
        fare("FCO", "CPH", "2026-12-01", 10),   # 50 notti
    ]
    args = (["CPH"], ["FCO"], 100, 3, True)
    assert [o.price for o in combine_one_way(fares, *args, max_nights=14)] == [50]
    got = combine_one_way(fares, *args)
    assert len(got) == 2
    o = filter_offers(offers(item(40, ret="2026-10-28T10:00:00+02:00")), cfg(), TODAY, TODAY + dt.timedelta(days=30))
    assert o == []  # 16 notti > 14


def test_pick_top_unique():
    from scanner.search import pick_top
    fares = [
        fare("CPH", "FCO", "2026-10-27", 30), fare("CPH", "FCO", "2026-10-28", 45),
        fare("FCO", "CPH", "2026-11-03", 40), fare("FCO", "CPH", "2026-11-04", 50),
    ]
    combos = sorted(combine_one_way(fares, ["CPH"], ["FCO"], 100, 3, True), key=lambda o: o.price)
    assert len(combos) == 4
    top = pick_top(combos, 10, True)
    assert [o.price for o in top] == [70, 95]      # 27→03 e 28→04, nessuna gamba ripetuta
    assert len(pick_top(combos, 10, False)) == 4


class FakeRyanair2:
    def search_month(self, o, d, m):
        if m != "2026-10":
            return []
        return {
            ("CPH", "FCO"): [fare("CPH", "FCO", "2026-10-12", 20), fare("CPH", "FCO", "2026-10-13", 30)],
            ("FCO", "CPH"): [fare("FCO", "CPH", "2026-10-17", 25)],
            ("CPH", "MXP"): [fare("CPH", "MXP", "2026-10-12", 90)],   # sopra soglia
            ("MXP", "CPH"): [fare("MXP", "CPH", "2026-10-17", 80)],
        }.get((o, d), [])


def test_rejection_reasons():
    from collections import Counter
    c = cfg()
    rej = Counter()
    start, end = TODAY + dt.timedelta(days=1), TODAY + dt.timedelta(days=30)
    filter_offers(
        offers(item(80, ret="2026-10-14T19:00:00+02:00"), item(70, transfers=2),
               item(60, ret="2026-11-02T19:00:00+01:00"), item(50, dep="2026-12-01T08:00:00+01:00", ret="2026-12-05T08:00:00+01:00")),
        c, start, end, ignore_price=True, rejected=rej,
    )
    assert rej == Counter({"notti fuori range": 2, "troppi scali": 1, "fuori finestra": 1})


def test_exclude_next_days(capsys):
    c = cfg(request_delay_seconds=0)
    c.search.window_days, c.search.exclude_next_days = 60, 15
    seen = []

    class C:
        def search_month(self, o, d, m):
            seen.append(m)
            return offers(
                item(50, dep="2026-10-12T08:00:00+02:00", ret="2026-10-17T08:00:00+02:00"),  # giorno 7: escluso
                item(60, dep="2026-10-25T08:00:00+01:00", ret="2026-10-30T08:00:00+01:00"),  # giorno 20: ok
            )
    top = run_search(c, client=C(), today=TODAY)
    assert [o.price for o in top] == [60]
    assert "2026-10-21" in capsys.readouterr().out    # prima partenza = oggi + 1 + 15


# --- Google Flights (fast-flights) ---

def _gf(price, airlines, legs):
    from fast_flights.model import Airport, Flights, SimpleDatetime, SingleFlight, CarbonEmission
    sf = [
        SingleFlight(Airport("x", o), Airport("x", d), SimpleDatetime(dd, dt_), SimpleDatetime(ad, at), dur, "A320")
        for o, d, dd, dt_, ad, at, dur in legs
    ]
    return Flights("best", price, airlines, sf, CarbonEmission(1, 1))


def test_parse_google_flights():
    from scanner.google_flights import parse_flights
    res = [
        _gf(39, ["Wizz Air"], [("CPH", "FCO", (2026, 10, 31), (16, 35), (2026, 10, 31), (19, 10), 155)]),
        _gf(60, ["Wizz Air", "SAS"], [("CPH", "ARN", (2026, 10, 31), (8, 0), (2026, 10, 31), (9, 30), 90),
                                      ("ARN", "FCO", (2026, 10, 31), (11, 0), (2026, 10, 31), (14, 30), 210)]),
        _gf(30, ["Wizz Air"], [("CPH", "CIA", (2026, 10, 31), (7, 0), (2026, 10, 31), (9, 30), 150)]),  # altro aeroporto
    ]
    got = parse_flights(res, "CPH", "FCO", "https://g/x", "EUR")
    assert [f.price for f in got] == [39, 60]
    assert got[0].arrival_at.hour == 19 and got[0].transfers == 0 and got[0].source == "google"
    assert got[1].transfers == 1 and got[1].duration == 300 and got[1].airline == "Wizz Air + SAS"


def test_google_client_uses_getter_and_handles_errors():
    from scanner.google_flights import GoogleFlightsClient
    from scanner.travelpayouts import ApiError
    c = GoogleFlightsClient(getter=lambda q: [_gf(39, ["Wizz Air"], [("CPH", "FCO", (2026, 10, 31), (16, 35), (2026, 10, 31), (19, 10), 155)])])
    got = c.search_day("CPH", "FCO", dt.date(2026, 10, 31))
    assert len(got) == 1 and got[0].link.startswith("https://www.google.com/travel/flights")

    def boom(q):
        raise RuntimeError("blocked")
    try:
        GoogleFlightsClient(getter=boom).search_day("CPH", "FCO", dt.date(2026, 10, 31))
        assert False
    except ApiError:
        pass


def test_run_search_google_combines_with_other_carriers():
    from scanner.config import GoogleFlightsConfig

    class FakeGoogle:
        def search_day(self, o, d, day):
            if (o, d) == ("CPH", "FCO") and str(day) == "2026-10-31":
                return [_g("CPH", "FCO", "2026-10-31T16:35:00", 33.91, "Wizz Air")]
            if (o, d) == ("FCO", "CPH") and str(day) == "2026-11-07":
                return [_g("FCO", "CPH", "2026-11-07T19:50:00", 53.09, "Wizz Air")]
            return []

    def _g(o, d, when, price, airline):
        return OneWayFare(o, d, dt.datetime.fromisoformat(when), price, airline, "https://g", source="google")

    c = Config(
        search=SearchConfig(max_price=100, min_nights=3, max_nights=14, window_days=30, request_delay_seconds=0),
        airports=AirportsConfig(origins=["CPH"], destinations=["FCO"]),
        sources=SourcesConfig(travelpayouts=False, ryanair=False, google_flights=True),
        google=GoogleFlightsConfig(workers=2, delay_seconds=0),
    )
    top = run_search(c, google=FakeGoogle(), today=TODAY)
    assert [o.price for o in top] == [87.0]
    assert top[0].airline == "Wizz Air" and top[0].source == "google" and top[0].nights == 7


def test_google_tasks_ranges():
    from scanner.search import google_tasks
    c = cfg()
    c.search.window_days = 10
    c.google.date_step = 1
    tasks = google_tasks(c, [("CPH", "NAP")], TODAY + dt.timedelta(days=1), TODAY + dt.timedelta(days=10))
    outs = [t for t in tasks if t[0] == "CPH"]
    rets = [t for t in tasks if t[0] == "NAP"]
    assert len(outs) == 10 and min(t[2] for t in rets) == TODAY + dt.timedelta(days=1 + 3)
    assert max(t[2] for t in rets) == TODAY + dt.timedelta(days=10 + 14)
    c.google.max_queries = 5
    assert len(google_tasks(c, [("CPH", "NAP")], TODAY + dt.timedelta(days=1), TODAY + dt.timedelta(days=10))) == 5


def test_google_bad_page_is_explained(monkeypatch):
    import scanner.google_flights as gf
    from scanner.travelpayouts import ApiError
    monkeypatch.setattr(gf, "fetch_html", lambda q: "<html><title>Before you continue</title>consent.google.com</html>")
    c = gf.GoogleFlightsClient()
    try:
        c.search_day("CPH", "FCO", dt.date(2026, 10, 31))
        assert False
    except ApiError as exc:
        assert "consenso" in str(exc) and "Before you continue" in str(exc)


def _raw_flight(price, code_from="CPH", code_to="NAP", dep=(16, 35), arr=(19, 10)):
    seg = [None] * 22
    seg[3], seg[4], seg[5], seg[6] = code_from, "from", "to", code_to
    seg[8], seg[10], seg[11], seg[17] = list(dep), list(arr), 155, "A320"
    seg[20], seg[21] = [2026, 10, 31], [2026, 10, 31]
    flight = ["best", ["Wizz Air"], [seg]] + [None] * 19 + [[0] * 9]
    return [flight, [[None, price]] if price is not None else [[]]]


def _js(entries):
    import json
    payload = [[None, None, 0, "tok", "x" * 52], None, None, [entries], None, None, None, [None, [[], []]]]
    return "AF_initDataCallback({key: 'ds:1', hash: '9', data:" + json.dumps(payload) + ", sideChannel: {}});"


def test_tolerant_parser_skips_flights_without_price():
    import scanner.google_flights as gf
    res = gf.parse_js_tolerant(_js([_raw_flight(39), _raw_flight(None), _raw_flight(55)]))
    assert [f.price for f in res] == [39, 55] and res[0].flights[0].departure.time == (16, 35)
    assert gf.parse_js_tolerant(_js(None)) == []


def test_parse_any_script_tries_other_blocks():
    import scanner.google_flights as gf
    good = _js([_raw_flight(39)])
    html = f'<html><script class="ds:0">data:BAD</script><script class="ds:1">{good}</script></html>'
    assert [f.price for f in gf.parse_any_script(html)] == [39]
    try:
        gf.parse_any_script("<html><script class='ds:0'>data:BAD</script></html>")
        assert False
    except ValueError:
        pass


def test_google_default_has_no_airline_filter():
    from scanner.config import GoogleFlightsConfig
    assert GoogleFlightsConfig().airlines == []


def test_parse_any_script_ignores_junk_blocks_before_results():
    """I blocchi ds:0/2/3/4 (paesi, valute, lingue) vengono prima di ds:1 e non devono vincere."""
    import json
    import scanner.google_flights as gf

    def blk(k, data):
        return f"<script class='{k}'>AF_initDataCallback({{key: '{k}', data:{json.dumps(data)}, sideChannel: {{}}}});</script>"

    junk = (
        blk("ds:0", [[None, None, 0, "id"], [2, [None]]])
        + blk("ds:2", [["AF", "Afghanistan"], ["AL", "Albania"], ["DZ", "Algeria"], ["AS", "Samoa"]])
        + blk("ds:3", [["ALL", "Lek", "ALL", 0], ["DZD", "Dinar", "DZD", 0], ["ARS", "Peso", "ARS", 0], ["AMD", "Dram", "AMD", 0]])
    )
    real = f'<script class="ds:1">{_js([_raw_flight(39), _raw_flight(None)])}</script>'
    got = gf.parse_any_script("<html>" + junk + real + "</html>")
    assert [f.price for f in got] == [39] and got.total == 2 and got.skipped == 1

    # pagina "nessun volo": ds:1 con struttura giusta ma senza voci -> vuota, non errore
    empty = f'<script class="ds:1">{_js(None)}</script>'
    assert list(gf.parse_any_script("<html>" + junk + empty + "</html>")) == []


def test_parse_any_script_ignores_airport_info_block_with_list_entries():
    """Il blocco ds:0 (info aeroporti) ha liste in payload[2]/[3]: non deve essere scambiato per i voli."""
    import json
    import scanner.google_flights as gf

    info = [[None, None, 0, "id"], [2, [None]], [[["CPH", 0], "Copenhagen Airport", ["/m/x", "Copenhagen"]]],
            [["/g/y", 4], "Naples", ["/g/y", "Naples"]]]
    junk = f"<script class='ds:0'>AF_initDataCallback({{key: 'ds:0', data:{json.dumps(info)}, sideChannel: {{}}}});</script>"
    real = f'<script class="ds:1">{_js([_raw_flight(39)])}</script>'
    got = gf.parse_any_script("<html>" + junk + real + "</html>")
    assert [f.price for f in got] == [39]


def test_empty_results_page_is_no_flights_not_error():
    """Pagina reale "nessun volo": payload[2]/[3] vuoti, ma l'intestazione dei risultati c'è."""
    import json
    import scanner.google_flights as gf

    empty = [[None, [1, 2, 3, 4, 5, 6], 0, "ad3Eav7OEc-ThcIP8JfHmAQ", "x" * 52], [[1, 2]], None, None, None, None,
             [[1, 2, 3, 4, 5]], [None, [1], None, None, None, [1, 2, 3, 4], None, [1]], None, None, None, None]
    blk = f"<script class='ds:1'>AF_initDataCallback({{key: 'ds:1', data:{json.dumps(empty)}, sideChannel: {{}}}});</script>"
    airports = [[None, None, 0, "id"], [2, [None]], [[["CPH", 0], "Copenhagen"]], [["/g/y", 4], "Naples"]]
    junk = f"<script class='ds:0'>AF_initDataCallback({{key: 'ds:0', data:{json.dumps(airports)}, sideChannel: {{}}}});</script>"
    assert list(gf.parse_any_script("<html>" + junk + blk + "</html>")) == []
    try:
        gf.parse_any_script("<html>" + junk + "</html>")   # senza blocco risultati: errore vero
        assert False
    except ValueError:
        pass


def test_report_has_top_and_per_airport_results_ignoring_budget():
    from scanner.report import SearchReport
    cfg = Config(
        search=SearchConfig(max_price=60, min_nights=3, window_days=30,
                            request_delay_seconds=0, top_per_airport=2),
        airports=AirportsConfig(origins=["CPH"], destinations=["FCO", "MXP", "NAP"]),
        sources=SourcesConfig(travelpayouts=False, ryanair=True, google_flights=False, open_jaw=False),
    )
    report = SearchReport()
    top = run_search(cfg, ryanair=FakeRyanair2(), today=TODAY, report=report)
    assert [o.price for o in top] == [45]
    assert [o.price for o in report.per_airport["FCO"]] == [45]
    assert [o.price for o in report.per_airport["MXP"]] == [170]
    assert report.per_airport["NAP"] == []
    # Reusing a leg and exceeding the deal budget must not discard saved results.
    assert [o.price for o in report.flights] == [45, 55, 170]


def test_quote_variants_are_preserved_while_exact_duplicates_are_removed():
    from dataclasses import replace
    original = offers(item(80))[0]
    rows = [original, replace(original), replace(original, price=90),
            replace(original, source="google"), replace(original, airline="U2")]
    result = filter_offers(rows, cfg(), TODAY, TODAY + dt.timedelta(days=30))
    assert len(result) == 4
    assert {row.price for row in result} == {80, 90}
    assert {row.airline for row in result} == {"FR", "U2"}
    assert {row.source for row in result} == {"travelpayouts", "google"}
