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
        sources=SourcesConfig(ryanair=False),
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


def test_run_search(capsys):
    c = cfg(request_delay_seconds=0)
    fc = FakeClient()
    top = run_search(c, client=fc, today=TODAY)
    assert len(fc.calls) == 2 and len(top) == 1 and top[0].price == 60
    assert "€  60.00" in capsys.readouterr().out


def fare(o, d, day, price):
    return OneWayFare(o, d, dt.datetime.fromisoformat(f"{day}T07:00:00"), price, "FR", f"https://r/originIata={o}")


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
    assert jaw.open_jaw and jaw.return_origin == "MXP" and "ritorno MXP→CPH" in jaw.summary
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
        sources=SourcesConfig(travelpayouts=False, ryanair=True, open_jaw=True),
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


def test_leg_prices_shown(capsys):
    from scanner.output import render_results
    o = combine_one_way([fare("CPH", "FCO", "2026-10-12", 20), fare("FCO", "CPH", "2026-10-17", 25)],
                        ["CPH"], ["FCO"], 100, 3, True)
    render_results(o, 100, 10)
    out = capsys.readouterr().out
    assert "€20.00" in out and "€25.00" in out and "Ryanair" in out
    lines = out.splitlines()
    i = next(n for n, l in enumerate(lines) if "Andata:" in l)
    assert "originIata=CPH" in lines[i + 1] and "Ritorno:" in lines[i + 2] and "originIata=FCO" in lines[i + 3]


def test_arrival_in_output(capsys):
    from scanner.output import render_results
    o = offers(item(80, dep="2026-10-12T22:30:00+02:00", duration_to=175))[0]
    render_results([o], 100, 10)
    out = capsys.readouterr().out
    assert "22:30 CPH → 01:25 (+1) NAP" in out


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


def _file_cfg(path, fmt, per_airport=2):
    from scanner.config import OutputConfig
    return Config(
        search=SearchConfig(max_price=60, min_nights=3, window_days=30, request_delay_seconds=0),
        airports=AirportsConfig(origins=["CPH"], destinations=["FCO", "MXP", "NAP"]),
        sources=SourcesConfig(travelpayouts=False, ryanair=True, open_jaw=False),
        output=OutputConfig(file=str(path), format=fmt, top_per_airport=per_airport),
    )


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


def test_file_has_top_and_per_airport_ignoring_threshold(tmp_path, capsys):
    import csv
    import json
    out = tmp_path / "r.txt"
    top = run_search(_file_cfg(out, "txt"), ryanair=FakeRyanair2(), today=TODAY)
    assert [o.price for o in top] == [45]            # CLI/top: solo ≤ soglia (60), 1 volo ripetuto escluso
    txt = out.read_text(encoding="utf-8")
    assert "Migliori 1 offerte" in txt and "RIEPILOGO PER AEROPORTO" in txt
    assert "### FCO — migliori 1" in txt and "### MXP — migliori 1" in txt and "€ 170.00" in txt  # MXP 90+80 oltre soglia
    assert "### NAP — nessun volo trovato" in txt
    assert "RIEPILOGO" not in capsys.readouterr().out   # il terminale resta com'era

    out = tmp_path / "r.csv"
    run_search(_file_cfg(out, "csv"), ryanair=FakeRyanair2(), today=TODAY)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["section"] for r in rows] == ["top", "aeroporto", "aeroporto"]
    assert [r["airport"] for r in rows if r["section"] == "aeroporto"] == ["FCO", "MXP"]

    out = tmp_path / "r.json"
    run_search(_file_cfg(out, "json"), ryanair=FakeRyanair2(), today=TODAY)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"top", "per_airport"} and list(data["per_airport"]) == ["FCO", "MXP", "NAP"]

    out = tmp_path / "off.txt"
    run_search(_file_cfg(out, "txt", per_airport=0), ryanair=FakeRyanair2(), today=TODAY)
    assert "RIEPILOGO" not in out.read_text(encoding="utf-8")
