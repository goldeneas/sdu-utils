"""Hosted export must distinguish an empty search from a failed refresh."""
import copy
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.config import AirportsConfig, Config, SearchConfig, SourcesConfig, load_config
from scanner.models import FlightOption
from scanner.publish import load_previous, publish
from scanner.report import SearchReport, SourceReport
from scanner.search import run_search
from scanner.travelpayouts import ApiError

NOW = dt.datetime(2026, 11, 10, 3, 15, tzinfo=dt.timezone.utc)


def config():
    return Config(
        airports=AirportsConfig(origins=["CPH", "MMX"], destinations=["FCO", "NAP"]),
        sources=SourcesConfig(travelpayouts=False, google_flights=False),
        search=SearchConfig(request_delay_seconds=0),
    )


def flight(price=70):
    return FlightOption("MMX", "FCO", dt.datetime(2026, 11, 20, 8),
                        dt.datetime(2026, 11, 27, 18), price, return_origin="NAP",
                        return_link="https://www.ryanair.com/back", link="https://www.ryanair.com/out")


def good_runner(cfg, *, today, report):
    assert today == NOW.date()
    report.sources = {"ryanair": SourceReport(succeeded=4)}
    report.per_airport = {"FCO": [flight()], "NAP": [flight(170)]}
    report.flights = [flight(), flight(170)]
    return [flight()]


def test_public_snapshot_has_itineraries_metadata_and_no_credentials(tmp_path, monkeypatch):
    cfg = config()
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "private-provider-token")
    out = tmp_path / "data/flights.json"
    data = publish(cfg, out, runner=good_runner, now=NOW)
    assert data == json.loads(out.read_text())
    assert data["status"] == "ok" and data["generated_at"] == NOW.isoformat(timespec="seconds")
    assert data["search"]["origins"] == ["CPH", "MMX"]
    assert data["search"]["departure_from"] == "2026-11-11"
    assert data["top"][0]["open_jaw"] and data["top"][0]["return_origin"] == "NAP"
    assert data["per_airport"]["NAP"][0]["price"] == 170
    assert [f["price"] for f in data["flights"]] == [70, 170]
    assert "private-provider-token" not in out.read_text()
    assert not out.with_suffix(".json.tmp").exists()


def test_failure_preserves_snapshot_timestamp_and_old_search_config(tmp_path):
    out = tmp_path / "flights.json"
    previous = publish(config(), out, runner=good_runner, now=NOW)
    original = copy.deepcopy(previous)

    def broken(*args, **kw):
        raise RuntimeError("secret provider request details")

    later = NOW + dt.timedelta(days=1)
    cfg = config()
    cfg.search.max_price = 500
    data = publish(cfg, out, previous, runner=broken, now=later)
    assert data["status"] == "stale" and data["generated_at"] == previous["generated_at"]
    assert data["attempted_at"] == later.isoformat(timespec="seconds")
    assert data["search"]["max_price"] == previous["search"]["max_price"]
    assert data["top"] == previous["top"] and previous == original
    assert "secret" not in out.read_text()


def test_total_request_failure_is_not_a_successful_empty_search(tmp_path):
    def failed(cfg, *, today, report):
        report.sources = {"ryanair": SourceReport(failed=4)}
        return []

    data = publish(config(), tmp_path / "flights.json", runner=failed, now=NOW)
    assert data["status"] == "unavailable" and data["generated_at"] is None


def test_healthy_empty_scan_replaces_old_results(tmp_path):
    out = tmp_path / "flights.json"
    previous = publish(config(), out, runner=good_runner, now=NOW)

    def empty(cfg, *, today, report):
        report.sources = {"ryanair": SourceReport(succeeded=4)}
        report.per_airport = {"FCO": [], "NAP": []}
        return []

    data = publish(config(), out, previous, runner=empty, now=NOW)
    assert data["status"] == "ok" and data["top"] == []


def test_partial_scan_and_no_deals_with_more_expensive_options(tmp_path):
    def partial(cfg, *, today, report):
        report.sources = {"ryanair": SourceReport(succeeded=2, failed=2)}
        report.per_airport = {"FCO": [flight(170)]}
        return []

    data = publish(config(), tmp_path / "flights.json", runner=partial, now=NOW)
    assert data["status"] == "partial" and data["top"] == []
    assert data["per_airport"]["FCO"][0]["price"] == 170


def test_empty_partial_scan_preserves_previous_results(tmp_path):
    out = tmp_path / "flights.json"
    previous = publish(config(), out, runner=good_runner, now=NOW)

    def partial(cfg, *, today, report):
        report.sources = {"ryanair": SourceReport(succeeded=2, failed=2)}
        return []

    assert publish(config(), out, previous, runner=partial, now=NOW)["status"] == "stale"


def test_missing_optional_token_does_not_stop_other_sources(tmp_path, monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    cfg = config()
    cfg.sources.travelpayouts = True

    def runner(cfg, **kw):
        assert not cfg.sources.travelpayouts and cfg.sources.ryanair
        return good_runner(cfg, **kw)

    data = publish(cfg, tmp_path / "flights.json", runner=runner, now=NOW)
    assert data["status"] == "partial" and data["skipped_sources"] == ["travelpayouts"]
    assert cfg.sources.travelpayouts


def test_missing_optional_token_does_not_turn_a_healthy_empty_scan_into_a_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    cfg = config()
    cfg.sources.travelpayouts = True

    def empty(cfg, *, today, report):
        report.sources = {"ryanair": SourceReport(succeeded=4)}
        return []

    data = publish(cfg, tmp_path / "flights.json", runner=empty, now=NOW)
    assert data["status"] == "partial" and data["generated_at"] is not None


def test_previous_must_be_a_valid_snapshot(tmp_path):
    out = tmp_path / "previous.json"
    assert load_previous(str(out)) is None
    for content in ("broken", "[]", '{"schema_version": 1}', '{"schema_version":1,"generated_at":2,"top":[],"per_airport":{},"search":{}}'):
        out.write_text(content)
        assert load_previous(str(out)) is None
    data = publish(config(), out, runner=good_runner, now=NOW)
    assert load_previous(str(out)) == data


def test_malmo_is_an_origin_in_the_repository_config():
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    assert cfg.airports.origins == ["BLL", "CPH", "MMX"]


def test_report_tracks_source_failures_even_when_run_search_catches_them():
    class Ryanair:
        def search_month(self, origin, destination, month):
            if origin == "MMX":
                raise ApiError("provider down")
            return []

    cfg = config()
    report = SearchReport()
    assert run_search(cfg, ryanair=Ryanair(), today=NOW.date(), report=report) == []
    assert report.sources["ryanair"].succeeded > 0
    assert report.sources["ryanair"].failed > 0
    assert report.per_airport == {"FCO": [], "NAP": []}


def test_google_report_tracks_aborted_requests():
    from scanner.config import GoogleFlightsConfig
    from scanner.search import _collect_google

    class Google:
        def search_day(self, *args):
            raise ApiError("blocked")

    cfg = config()
    cfg.google = GoogleFlightsConfig(workers=1, delay_seconds=0)
    report = SourceReport()
    assert _collect_google(cfg, Google(), [("MMX", "FCO")], NOW.date(), NOW.date()+dt.timedelta(days=6), report) == []
    assert report.aborted and report.failed >= 10 and report.succeeded == 0


def test_scheduled_entry_point_reads_config_and_previous_snapshot(tmp_path, monkeypatch):
    import runpy
    import scanner.search

    previous_path = tmp_path / "previous.json"
    previous = publish(config(), previous_path, runner=good_runner, now=NOW)
    (tmp_path / "config.yaml").write_text(
        "airports:\n  origins: [MMX]\n  destinations: [FCO]\n"
        "sources:\n  travelpayouts: false\n  ryanair: true\n  google_flights: false\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PREVIOUS_FLIGHTS_PATH", str(previous_path))

    def failed(cfg, *, today, report):
        assert cfg.airports.origins == ["MMX"]
        report.sources = {"ryanair": SourceReport(failed=1)}
        return []

    monkeypatch.setattr(scanner.search, "run_search", failed)
    monkeypatch.delitem(sys.modules, "scanner.publish")
    runpy.run_module("scanner.publish", run_name="__main__")
    data = json.loads((tmp_path / "data/flights.json").read_text())
    assert data["status"] == "stale"
    assert data["top"] == previous["top"]
    assert data["generated_at"] == previous["generated_at"]


def test_per_destination_limit_is_read_and_validated(tmp_path):
    import pytest

    path = tmp_path / "config.yaml"
    base = "airports:\n  origins: [MMX]\n  destinations: [FCO]\n"
    path.write_text(base + "search:\n  top_per_airport: 5\n")
    assert load_config(path).search.top_per_airport == 5
    path.write_text(base + "search:\n  top_per_airport: 0\n")
    with pytest.raises(ValueError, match="top_per_airport"):
        load_config(path)


def test_all_results_are_exported_before_budget_highlight_and_unique_leg_limits(tmp_path, monkeypatch):
    cfg = config()
    cfg.sources = SourcesConfig(travelpayouts=True, ryanair=False, google_flights=False)
    cfg.search.top_n = cfg.search.top_per_airport = 1
    cfg.search.unique_flights = True
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "test-only")

    class Provider:
        def search_month(self, origin, destination, month):
            if (origin, destination, month) != ("MMX", "FCO", "2026-11"):
                return []
            rows = []
            for i in range(35):
                row = flight(50 + i * 8)
                row.departure_at += dt.timedelta(hours=i)
                rows.append(row)
            return rows

    def runner(cfg, *, today, report):
        return run_search(cfg, client=Provider(), today=today, report=report)

    data = publish(cfg, tmp_path / "flights.json", runner=runner, now=NOW)
    assert len(data["top"]) == len(data["per_airport"]["FCO"]) == 1
    assert len(data["flights"]) == 35
    assert [row["price"] for row in data["flights"]] == list(range(50, 50 + 35 * 8, 8))
