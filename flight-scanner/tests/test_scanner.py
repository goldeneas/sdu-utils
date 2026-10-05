import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.config import AirportsConfig, Config, SearchConfig  # noqa: E402
from scanner.search import filter_offers, months_in_window, run_search  # noqa: E402
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
    )


def offers(*items):
    return [parse_offer(i, "CPH", "NAP", "EUR") for i in items]


def test_parse_offer():
    o = parse_offer(item(79), "CPH", "NAP", "EUR")
    assert o.price == 79 and o.nights == 5 and o.departure_at.hour == 8
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
            item(100, airline="W6"),                                              # = soglia, incluso
        ),
        c, start, end,
    )
    assert [o.price for o in got] == [79.0, 100.0]


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
