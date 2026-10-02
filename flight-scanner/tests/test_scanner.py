"""Unit tests for the pure logic (no network access).

``conftest.py`` puts ``src/`` on ``sys.path`` so ``flight_scanner`` imports
resolve; the pyright ignore mirrors that for the static checker.

Run with:  python3 -m unittest discover -s tests -v
"""
# pyright: reportMissingImports=false

import unittest
from datetime import date
from unittest import mock

from flight_scanner import ground, ryanair, scan


class TestRyanairHelpers(unittest.TestCase):
    def test_months_between_spans_year_boundary(self):
        self.assertEqual(
            ryanair.months_between(date(2026, 11, 5), date(2027, 2, 1)),
            ["2026-11-01", "2026-12-01", "2027-01-01", "2027-02-01"],
        )

    def test_iata_validation(self):
        ryanair._check_iata("CPH")  # must not raise
        for bad in ("nap", "CPHX", "", "../../x", "C1H"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ryanair._check_iata(bad)


class TestScanHelpers(unittest.TestCase):
    def test_flight_hours_normal(self):
        self.assertAlmostEqual(scan._hhmm_to_hours("16:35", "19:10"), 155 / 60)

    def test_flight_hours_crosses_midnight(self):
        self.assertAlmostEqual(scan._hhmm_to_hours("23:30", "01:00"), 1.5)

    def test_flight_hours_unknown_schedule_falls_back(self):
        self.assertEqual(scan._hhmm_to_hours("", ""), 2.5)

    def test_build_legs_adds_fare_and_ground_costs(self):
        fare = ryanair.Fare(
            origin="CPH",
            dest="FCO",
            day="2026-12-05",
            price=27.99,
            depart_time="16:35",
            arrive_time="19:10",
        )
        legs = scan.build_legs(
            "out", "CPH", "FCO", [fare], overhead_h=2.5, pickup=False
        )
        self.assertEqual(len(legs), 1)
        leg = legs[0]
        expected_cost = (
            27.99
            + ground.ODENSE_TO_AIRPORT["CPH"].cost_min
            + ground.ITALY_AIRPORT_TO_SALERNO["FCO"].cost_min
        )
        self.assertAlmostEqual(leg.cost, round(expected_cost, 2), places=2)
        expected_hours = (
            2.5
            + ground.ODENSE_TO_AIRPORT["CPH"].hours
            + 155 / 60
            + ground.ITALY_AIRPORT_TO_SALERNO["FCO"].hours
        )
        self.assertAlmostEqual(leg.hours, expected_hours, delta=0.01)

    def test_build_legs_returns_empty_without_ground_data(self):
        fare = ryanair.Fare("CPH", "XXX", "2026-12-05", 10.0, "10:00", "11:00")
        self.assertEqual(scan.build_legs("out", "CPH", "XXX", [fare], 2.5, False), [])

    @staticmethod
    def _leg(kind, day, fare, cost, hours):
        return scan.Leg(
            kind=kind,
            fly_from="CPH",
            fly_to="NAP",
            day=day,
            fare=fare,
            depart="10:00",
            arrive="12:00",
            flight_h=2.0,
            ground_from="train",
            ground_to="bus",
            cost=cost,
            hours=hours,
        )

    def test_combine_filters_by_trip_length_and_ranks_by_score(self):
        out_legs = [self._leg("out", "2026-12-10", 30, 80, 8)]
        back_legs = [
            self._leg("back", "2026-12-15", 30, 80, 8),  # 5 days -> out
            self._leg("back", "2027-01-05", 40, 90, 9),  # 26 days -> out
            self._leg("back", "2026-12-24", 35, 85, 8.5),  # 14 days -> kept
        ]
        trips = scan.combine(
            out_legs, back_legs, time_value=8, trip_min=10, trip_max=25
        )
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0].days, 14)
        self.assertAlmostEqual(trips[0].cost, 165)

    def test_time_value_changes_ordering(self):
        out_fast = [self._leg("out", "2026-12-10", 100, 150, 4)]
        back_fast = [self._leg("back", "2026-12-24", 100, 150, 4)]
        out_slow = [self._leg("out", "2026-12-10", 10, 60, 20)]
        back_slow = [self._leg("back", "2026-12-24", 10, 60, 20)]

        cheap = scan.combine(out_slow, back_slow, 0, 10, 25)[0]
        fast = scan.combine(out_fast, back_fast, 0, 10, 25)[0]
        self.assertLess(cheap.cost, fast.cost)

        both = scan.combine(
            out_fast + out_slow,
            back_fast + back_slow,
            time_value=20,
            trip_min=10,
            trip_max=25,
        )
        self.assertLess(both[0].hours, both[-1].hours)

    def test_pareto_front_keeps_only_non_dominated(self):
        def trip(cost, hours):
            return scan.Trip(
                self._leg("out", "2026-12-10", 10, cost, hours),
                self._leg("back", "2026-12-24", 10, 0, 0),
                cost,
                hours,
                14,
                cost + hours,
            )

        front = scan.pareto([trip(100, 20), trip(130, 10), trip(150, 15)])
        self.assertEqual([t.cost for t in front], [100, 130])


class TestGroundModel(unittest.TestCase):
    def test_naples_pickup_is_free(self):
        picked = ground.airport_to_salerno("NAP", pickup=True)
        assert picked is not None
        self.assertEqual(picked.cost_min, 0)
        self.assertEqual(picked.cost_typ, 0)

    def test_pickup_does_not_change_other_airports(self):
        self.assertEqual(
            ground.airport_to_salerno("FCO", pickup=False),
            ground.airport_to_salerno("FCO", pickup=True),
        )

    def test_unknown_iata_has_no_ground_leg(self):
        self.assertIsNone(ground.odense_to_airport("ZZZ"))
        self.assertIsNone(ground.airport_to_salerno("ZZZ"))


class TestRollingWindow(unittest.TestCase):
    def test_trip_window_is_relative_to_today(self):
        today = date(2026, 10, 1)
        out_start, out_end, ret_start, ret_end = scan.trip_window(30, 5, 9, today)
        self.assertEqual(out_start, today)
        self.assertEqual(out_end, date(2026, 10, 31))
        self.assertEqual(ret_start, date(2026, 10, 6))
        self.assertEqual(ret_end, date(2026, 11, 9))

    def test_enrich_flight_ids_uses_lookup(self):
        leg = scan.Leg(
            kind="out",
            fly_from="CPH",
            fly_to="FCO",
            day="2026-12-12",
            fare=28.0,
            depart="16:35",
            arrive="19:10",
            flight_h=2.5,
            ground_from="train",
            ground_to="train",
            cost=70.0,
            hours=9.0,
        )
        fare = ryanair.Fare(
            "CPH", "FCO", "2026-12-12", 28.0, "16:35", "19:10", flight_no="FR406"
        )
        with mock.patch.object(
            scan.ryanair, "fare_for_day", return_value=fare
        ) as lookup:
            scan.enrich_flight_ids([leg])
        self.assertEqual(leg.flight_no, "FR406")
        lookup.assert_called_once()

    def test_leg_summary_shows_cost_split(self):
        leg = scan.Leg(
            kind="out",
            fly_from="CPH",
            fly_to="FCO",
            day="2026-12-12",
            fare=28.0,
            depart="16:35",
            arrive="19:10",
            flight_h=2.5,
            ground_from="train",
            ground_to="train",
            cost=70.0,
            hours=9.0,
            flight_no="FR406",
            service_from="DSB IC/IR Odense->CPH",
            service_to="Leonardo Express + Frecciarossa",
        )
        text = scan.leg_summary(leg)
        self.assertIn("FR406", text)
        self.assertIn("air EUR28", text)
        self.assertIn("ground EUR42", text)
        self.assertIn("Leonardo Express", scan.leg_services(leg))

    def test_trip_cost_split(self):
        out = scan.Leg(
            kind="out",
            fly_from="CPH",
            fly_to="FCO",
            day="2026-12-12",
            fare=28.0,
            depart="16:35",
            arrive="19:10",
            flight_h=2.5,
            ground_from="train",
            ground_to="train",
            cost=70.0,
            hours=9.0,
        )
        back = scan.Leg(
            kind="back",
            fly_from="FCO",
            fly_to="CPH",
            day="2026-12-17",
            fare=21.0,
            depart="21:15",
            arrive="23:55",
            flight_h=2.5,
            ground_from="train",
            ground_to="train",
            cost=63.0,
            hours=9.0,
        )
        trip = scan.Trip(
            out=out, back=back, cost=133.0, hours=18.0, days=5, score=277.0
        )
        self.assertEqual(scan.trip_air_cost(trip), 49.0)
        self.assertEqual(scan.trip_ground_cost(trip), 84.0)
        self.assertIn("air EUR49 + ground EUR84", scan.trip_cost_line(trip))
        self.assertIn("air EUR49 + ground EUR84", scan.fmt_trip(trip))

    def test_ground_service_identifiers(self):
        self.assertIn("DSB", ground.odense_service("CPH"))
        self.assertIn("Leonardo Express", ground.airport_service("FCO"))
        self.assertEqual(
            ground.airport_service("NAP", pickup=True), "Family car pickup"
        )

    def test_ground_segments_are_bookable(self):
        fco = ground.airport_segments("FCO")
        self.assertEqual(len(fco), 2)
        self.assertEqual(fco[0].service, "Leonardo Express")
        self.assertEqual(fco[0].depart, "Fiumicino Aeroporto")
        self.assertIn("trenitalia.com", fco[0].book_at)
        picked = ground.airport_segments("NAP", pickup=True)
        self.assertEqual(picked[0].label(), "Family car pickup")

    def test_describe_ground_lists_segments(self):
        fare = ryanair.Fare("CPH", "FCO", "2026-12-01", 30.0, "10:00", "12:00")
        leg = scan.build_legs("out", "CPH", "FCO", [fare], 2.5, False)[0]
        text = "\n".join(scan.describe_ground(leg))
        self.assertIn("Odense St -> Koebenhavns Lufthavn", text)
        self.assertIn("Leonardo Express", text)
        self.assertIn("trenitalia.com", text)


if __name__ == "__main__":
    unittest.main()
