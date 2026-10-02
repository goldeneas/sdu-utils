"""Unit tests for the watcher: config, deal detection, state, notifications."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flight_scanner import config as config_mod
from flight_scanner import ground, notify, scan
from flight_scanner import state as state_mod
from flight_scanner.config import DealConfig
from flight_scanner.state import WatchState
from flight_scanner.watch import (
    Deal,
    apply_state,
    detect_deals,
    format_deal_notification,
    trip_signature,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def make_leg(
    kind,
    fly_from,
    fly_to,
    day,
    cost,
    hours=8.0,
    flight_no="",
    service_from="DSB IC/IR Odense->CPH",
    service_to="Leonardo Express + Frecciarossa",
):
    seg_from = ground.odense_segments(fly_from) or ground.airport_segments(fly_from)
    seg_to = ground.airport_segments(fly_to) or ground.odense_segments(fly_to)
    return scan.Leg(
        kind=kind,
        fly_from=fly_from,
        fly_to=fly_to,
        day=day,
        fare=cost - 20,
        depart="10:00",
        arrive="12:00",
        flight_h=2.0,
        ground_from="train",
        ground_to="bus",
        cost=cost,
        hours=hours,
        flight_no=flight_no,
        service_from=service_from,
        service_to=service_to,
        seg_from=seg_from,
        seg_to=seg_to,
    )


def make_trip(
    cost, out_day="2026-12-12", back_day="2027-01-06", hours=20.0, dest="FCO"
):
    out = make_leg("out", "CPH", dest, out_day, cost / 2)
    back = make_leg("back", dest, "CPH", back_day, cost / 2)
    days = (
        __import__("datetime").date.fromisoformat(back_day)
        - __import__("datetime").date.fromisoformat(out_day)
    ).days
    return scan.Trip(
        out=out, back=back, cost=cost, hours=hours, days=days, score=cost + 8 * hours
    )


def write_config(tmp: Path, body: str) -> Path:
    path = tmp / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


MINIMAL_CONFIG = """
[trip]
days = 30

[notify]
ntfy_topic = "my-long-random-topic"
"""


# --------------------------------------------------------------------------- #
# Signatures
# --------------------------------------------------------------------------- #
class TestTripSignature(unittest.TestCase):
    def test_same_shape_same_signature_regardless_of_price(self):
        self.assertEqual(trip_signature(make_trip(200)), trip_signature(make_trip(150)))

    def test_different_day_differs(self):
        self.assertNotEqual(
            trip_signature(make_trip(200, out_day="2026-12-12")),
            trip_signature(make_trip(200, out_day="2026-12-13")),
        )

    def test_different_airport_differs(self):
        self.assertNotEqual(
            trip_signature(make_trip(200, dest="FCO")),
            trip_signature(make_trip(200, dest="BGY")),
        )


# --------------------------------------------------------------------------- #
# Deal detection
# --------------------------------------------------------------------------- #
class TestDetectDeals(unittest.TestCase):
    def setUp(self):
        self.cfg = DealConfig(
            mode="both",
            max_total=250,
            improve_by=5,
            max_alerts=3,
            notify_first_run=True,
        )

    def test_first_run_alerts(self):
        deals = detect_deals([make_trip(180)], WatchState(), self.cfg)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0].reason, "first scan")
        self.assertIsNone(deals[0].previous)

    def test_first_run_silent_when_disabled(self):
        cfg = DealConfig(notify_first_run=False)
        self.assertEqual(detect_deals([make_trip(180)], WatchState(), cfg), [])

    def test_unchanged_second_run_is_silent(self):
        first = WatchState()
        deals = detect_deals([make_trip(180)], first, self.cfg)
        apply_state(first, [make_trip(180)], self.cfg.max_total)
        self.assertEqual(len(deals), 1)
        self.assertEqual(detect_deals([make_trip(180)], first, self.cfg), [])

    def test_new_best_triggers_when_cheaper_enough(self):
        memory = WatchState(best_total=200.0, deals={}, runs=1)
        deals = detect_deals([make_trip(190)], memory, self.cfg)
        self.assertEqual([d.reason for d in deals], ["new best"])
        self.assertEqual(deals[0].previous, 200.0)

    def test_small_improvement_is_ignored(self):
        memory = WatchState(best_total=200.0, deals={}, runs=1)
        cfg = DealConfig(
            mode="best",
            max_total=250,
            improve_by=5,
            max_alerts=3,
            notify_first_run=True,
        )
        self.assertEqual(detect_deals([make_trip(197)], memory, cfg), [])

    def test_price_drop_on_known_trip(self):
        sig = trip_signature(make_trip(180))
        memory = WatchState(best_total=180.0, deals={sig: 180.0}, runs=3)
        cfg = DealConfig(
            mode="threshold",
            max_total=250,
            improve_by=5,
            max_alerts=3,
            notify_first_run=True,
        )
        deals = detect_deals([make_trip(170)], memory, cfg)
        self.assertEqual([d.reason for d in deals], ["price drop"])

    def test_max_alerts_is_respected(self):
        trips = [make_trip(150 + i, out_day=f"2026-12-{12 + i}") for i in range(6)]
        cfg = DealConfig(
            mode="threshold",
            max_total=250,
            max_alerts=2,
            improve_by=5,
            notify_first_run=True,
        )
        deals = detect_deals(trips, WatchState(), cfg)
        self.assertEqual(len(deals), 2)
        self.assertLessEqual(deals[0].trip.cost, deals[1].trip.cost)

    def test_threshold_mode_ignores_best_above_threshold(self):
        cfg = DealConfig(
            mode="threshold",
            max_total=100,
            max_alerts=3,
            improve_by=5,
            notify_first_run=True,
        )
        self.assertEqual(detect_deals([make_trip(180)], WatchState(), cfg), [])

    def test_best_mode_ignores_threshold(self):
        cfg = DealConfig(
            mode="best", max_total=0, max_alerts=3, improve_by=5, notify_first_run=True
        )
        deals = detect_deals([make_trip(180)], WatchState(), cfg)
        self.assertEqual([d.reason for d in deals], ["first scan"])

    def test_no_trips_means_no_deals(self):
        self.assertEqual(detect_deals([], WatchState(), self.cfg), [])


class TestApplyState(unittest.TestCase):
    def test_records_best_total_and_increments_runs(self):
        memory = WatchState()
        apply_state(memory, [make_trip(180), make_trip(160)], 250)
        self.assertEqual(memory.best_total, 160)
        self.assertEqual(memory.runs, 1)
        self.assertTrue(memory.deals)
        self.assertTrue(memory.last_run)

    def test_best_total_only_moves_down(self):
        memory = WatchState(best_total=150.0, runs=1)
        apply_state(memory, [make_trip(180)], 250)
        self.assertEqual(memory.best_total, 150.0)

    def test_above_threshold_trips_are_not_recorded(self):
        memory = WatchState()
        apply_state(memory, [make_trip(999), make_trip(120)], 250)
        self.assertLessEqual(max(memory.deals.values()), 250)


# --------------------------------------------------------------------------- #
# State IO
# --------------------------------------------------------------------------- #
class TestStateIO(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "state.json"
            original = WatchState(best_total=123.45, deals={"x": 1.0}, runs=4)
            original.note_run()
            state_mod.save_state(path, original)
            loaded = state_mod.load_state(path)
            self.assertEqual(loaded.best_total, 123.45)
            self.assertEqual(loaded.deals, {"x": 1.0})
            self.assertEqual(loaded.runs, 5)

    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(state_mod.load_state(Path(tmp) / "nope.json").runs, 0)

    def test_corrupt_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(state_mod.load_state(path).best_total, None)

    def test_unknown_version_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                json.dumps({"version": 999, "best_total": 5}), encoding="utf-8"
            )
            self.assertIsNone(state_mod.load_state(path).best_total)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
class TestConfig(unittest.TestCase):
    def test_minimal_config_loads_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_mod.load_config(write_config(Path(tmp), MINIMAL_CONFIG))
        self.assertEqual(cfg.trip.days, 30)
        self.assertEqual(cfg.trip.origins, ("CPH", "AAR", "BLL"))
        self.assertEqual(cfg.deals.mode, "both")
        self.assertEqual(cfg.notify.ntfy_server, "https://ntfy.sh")
        self.assertTrue(cfg.trip.pickup_naples)
        self.assertEqual(cfg.state_file.name, "watch-state.json")

    def test_missing_channel_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = MINIMAL_CONFIG.replace('ntfy_topic = "my-long-random-topic"', "")
            with self.assertRaises(config_mod.ConfigError):
                config_mod.load_config(write_config(Path(tmp), body))

    def test_non_positive_days_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = MINIMAL_CONFIG.replace("days = 30", "days = 0")
            with self.assertRaises(config_mod.ConfigError):
                config_mod.load_config(write_config(Path(tmp), body))

    def test_reversed_trip_length_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = MINIMAL_CONFIG.replace("days = 30", "trip_min = 20\ntrip_max = 5")
            with self.assertRaises(config_mod.ConfigError):
                config_mod.load_config(write_config(Path(tmp), body))

    def test_stdout_only_is_a_valid_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = MINIMAL_CONFIG.replace(
                'ntfy_topic = "my-long-random-topic"', "stdout = true"
            )
            cfg = config_mod.load_config(write_config(Path(tmp), body))
            self.assertTrue(cfg.notify.has_any_channel())


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
class TestNotify(unittest.TestCase):
    def test_priority_rank(self):
        note = notify.Notification("t", "m", priority="max")
        self.assertEqual(note.priority_rank(), 5)
        self.assertEqual(notify.Notification("t", "m", priority="3").priority_rank(), 3)
        self.assertEqual(
            notify.Notification("t", "m", priority="bogus").priority_rank(), 3
        )

    def test_ntfy_payload(self):
        notifier = notify.NtfyNotifier("https://ntfy.sh", "topic", "tok")
        note = notify.Notification(
            "Title", "Body", priority="high", tags=("airplane",), click="https://x"
        )
        with mock.patch.object(notify, "_post_json") as post:
            notifier.send(note)
        url, payload, headers = post.call_args.args
        self.assertEqual(url, "https://ntfy.sh/")
        self.assertEqual(payload["topic"], "topic")
        self.assertEqual(payload["priority"], 4)
        self.assertEqual(payload["tags"], ["airplane"])
        self.assertEqual(headers, {"Authorization": "Bearer tok"})

    def test_non_https_url_is_rejected(self):
        with self.assertRaises(notify.NotifyError):
            notify._require_safe_url("http://evil.example/ntfy")

    def test_loopback_http_is_allowed(self):
        notify._require_safe_url("http://localhost:8080/")

    def test_send_all_collects_errors_without_raising(self):
        class Boom:
            name = "boom"

            def send(self, note):
                raise notify.NotifyError("nope")

        errors = notify.send_all([Boom()], notify.Notification("t", "m"))
        self.assertEqual(len(errors), 1)
        self.assertIn("boom", errors[0])


class TestFormatDealNotification(unittest.TestCase):
    def test_single_deal_title_and_body(self):
        cfg = config_mod.WatchConfig(
            trip=config_mod.TripConfig(),
            deals=DealConfig(),
            notify=config_mod.NotifyConfig(ntfy_topic="t", priority="high"),
            state_file=Path("watch-state.json"),
        )
        deal = Deal(make_trip(182.4), "first scan")
        note = format_deal_notification([deal], cfg)
        self.assertIn("182", note.title)
        self.assertIn("first scan", note.message)
        self.assertIn("CPH->FCO", note.message)
        self.assertEqual(note.priority, "high")

    def test_multiple_deals_title_counts(self):
        cfg = config_mod.WatchConfig(
            trip=config_mod.TripConfig(),
            deals=DealConfig(),
            notify=config_mod.NotifyConfig(ntfy_topic="t"),
            state_file=Path("watch-state.json"),
        )
        note = format_deal_notification(
            [Deal(make_trip(180), "a"), Deal(make_trip(200), "b")], cfg
        )
        self.assertIn("2 cheap trips", note.title)

    def test_notification_includes_ids_and_ground_hops(self):
        cfg = config_mod.WatchConfig(
            trip=config_mod.TripConfig(),
            deals=DealConfig(),
            notify=config_mod.NotifyConfig(ntfy_topic="t"),
            state_file=Path("watch-state.json"),
        )
        trip = make_trip(150)
        trip.out.flight_no = "FR406"
        note = format_deal_notification([Deal(trip, "first scan")], cfg)
        self.assertIn("FR406", note.message)
        self.assertIn("Leonardo Express", note.message)
        self.assertIn("air EUR", note.message)
        self.assertNotIn("typical EUR", note.message)


if __name__ == "__main__":
    unittest.main()
