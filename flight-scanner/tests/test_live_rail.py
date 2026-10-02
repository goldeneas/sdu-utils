"""Unit tests for the live rail/bus providers (no network)."""

import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from flight_scanner import live_rail as lr
from flight_scanner import scan

ZONE = ZoneInfo("Europe/Rome")


def make_leg(kind, fly_from, fly_to, day="2026-10-20", depart="16:35", arrive="19:10"):
    return scan.Leg(
        kind=kind,
        fly_from=fly_from,
        fly_to=fly_to,
        day=day,
        fare=30.0,
        depart=depart,
        arrive=arrive,
        flight_h=2.5,
        ground_from="train",
        ground_to="train",
        cost=70.0,
        hours=9.0,
    )


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = []

    def connections(self, origin, destination, when, *, arrive_by=False, limit=3):
        self.calls.append((origin, destination, arrive_by))
        return [
            lr.RailLeg(
                provider=self.name,
                mode="HIGHSPEED_RAIL",
                line="FR 9515",
                operator="TRENITALIA",
                depart_station=origin,
                arrive_station=destination,
                depart=when.isoformat(),
                arrive=when.isoformat(),
                duration_min=60,
            )
        ]


class TestBuildProvider(unittest.TestCase):
    def test_auto_uses_transitous_without_access_id(self):
        self.assertIsInstance(lr.build_provider("auto"), lr.TransitousProvider)

    def test_auto_uses_rejseplanen_with_access_id(self):
        provider = lr.build_provider("auto", rejseplanen_access_id="abc")
        self.assertIsInstance(provider, lr.RejseplanenProvider)

    def test_unknown_provider_rejected(self):
        with self.assertRaises(lr.ProviderUnavailable):
            lr.build_provider("nope")

    def test_rejseplanen_without_access_id_is_unavailable(self):
        with self.assertRaises(lr.ProviderUnavailable):
            lr.RejseplanenProvider("")

    def test_trainline_is_blocked(self):
        provider = lr.build_provider("trainline")
        with self.assertRaises(lr.ProviderBlocked):
            provider.connections("Roma Termini", "Salerno", datetime(2026, 10, 20, 9))


class TestLiveGroundRouting(unittest.TestCase):
    def test_outbound_uses_danish_to_airport_then_italian_to_salerno(self):
        danish, italian = FakeProvider(), FakeProvider()
        leg = make_leg("out", "CPH", "FCO")
        result = lr.live_ground_for_leg(leg, danish, italian)
        self.assertEqual(len(result["before_flight"]), 1)
        self.assertEqual(len(result["after_flight"]), 1)
        self.assertEqual(danish.calls[0][0], lr.ODENSE)
        self.assertEqual(danish.calls[0][1], lr.DK_STATION["CPH"])
        self.assertTrue(danish.calls[0][2])  # arrive_by
        self.assertEqual(italian.calls[0][0], lr.IT_STATION["FCO"])
        self.assertEqual(italian.calls[0][1], lr.SALERNO)
        self.assertFalse(italian.calls[0][2])

    def test_return_uses_italian_to_airport_then_danish_home(self):
        danish, italian = FakeProvider(), FakeProvider()
        leg = make_leg("back", "FCO", "CPH")
        result = lr.live_ground_for_leg(leg, danish, italian)
        self.assertEqual(italian.calls[0][0], lr.SALERNO)
        self.assertEqual(italian.calls[0][1], lr.IT_STATION["FCO"])
        self.assertTrue(italian.calls[0][2])
        self.assertEqual(danish.calls[0][0], lr.DK_STATION["CPH"])
        self.assertEqual(danish.calls[0][1], lr.ODENSE)
        self.assertFalse(danish.calls[0][2])
        self.assertEqual(len(result["before_flight"]), 1)

    def test_missing_provider_is_tolerated(self):
        leg = make_leg("out", "CPH", "FCO")
        result = lr.live_ground_for_leg(leg, None, None)
        self.assertEqual(result, {"before_flight": [], "after_flight": []})

    def test_provider_errors_are_swallowed(self):
        class Boom(FakeProvider):
            def connections(self, *a, **k):
                raise lr.ProviderUnavailable("down")

        leg = make_leg("out", "CPH", "FCO")
        result = lr.live_ground_for_leg(leg, Boom(), Boom())
        self.assertEqual(result, {"before_flight": [], "after_flight": []})

    def test_unknown_airport_yields_no_lookups(self):
        danish, italian = FakeProvider(), FakeProvider()
        leg = make_leg("out", "ZZZ", "FCO")
        result = lr.live_ground_for_leg(leg, danish, italian)
        self.assertEqual(result, {"before_flight": [], "after_flight": []})
        self.assertEqual(danish.calls, [])
        self.assertEqual(italian.calls, [])

    def test_pickup_naples_skips_italian_lookup(self):
        danish, italian = FakeProvider(), FakeProvider()
        leg = make_leg("out", "CPH", "NAP")
        result = lr.live_ground_for_leg(leg, danish, italian, pickup=True)
        self.assertEqual(italian.calls, [])  # parents collect -> no NAP lookup
        self.assertEqual(len(result["before_flight"]), 1)
        self.assertEqual(result["after_flight"], [])


class TestLiveGroundLines(unittest.TestCase):
    def test_lines_include_line_number_and_stations(self):
        leg = make_leg("out", "CPH", "FCO")
        lines = lr.live_ground_lines(leg, FakeProvider(), FakeProvider())
        text = "\n".join(lines)
        self.assertIn("FR 9515", text)
        self.assertIn("TRENITALIA", text)
        self.assertIn("train", text)


class TestTransitousParsing(unittest.TestCase):
    def _fake_request(self, url, **_):
        if "/geocode?" in url:
            return [{"lat": 41.9, "lon": 12.5}]
        return {
            "itineraries": [
                {
                    "legs": [
                        {"mode": "WALK", "startTime": "x", "endTime": "y"},
                        {
                            "mode": "HIGHSPEED_RAIL",
                            "routeShortName": "FR 9515",
                            "agencyName": "TRENITALIA",
                            "from": {"name": "ROMA TERMINI"},
                            "to": {"name": "SALERNO"},
                            "startTime": "2026-10-20T09:00:00+02:00",
                            "endTime": "2026-10-20T11:02:00+02:00",
                        },
                    ]
                }
            ]
        }

    def test_connections_parse_train_number_and_duration(self):
        provider = lr.TransitousProvider()
        with mock.patch.object(lr, "_request_json", side_effect=self._fake_request):
            legs = provider.connections(
                "Roma Termini", "Salerno", datetime(2026, 10, 20, 7, tzinfo=ZONE)
            )
        self.assertEqual(len(legs), 1)
        self.assertEqual(legs[0].line, "FR 9515")
        self.assertEqual(legs[0].operator, "TRENITALIA")
        self.assertEqual(legs[0].duration_min, 122)
        self.assertIn("FR 9515", legs[0].summary())

    def test_empty_itineraries_return_empty(self):
        provider = lr.TransitousProvider()
        with mock.patch.object(
            lr, "_request_json", side_effect=lambda url, **_: [{"lat": 1, "lon": 2}]
        ):
            legs = provider.connections(
                "A", "B", datetime(2026, 10, 20, 7, tzinfo=ZONE)
            )
        self.assertEqual(legs, [])


if __name__ == "__main__":
    unittest.main()
