"""Command-line interface.

Subcommands::

    init               write a starter config.toml (with a random ntfy topic)
    check              run one check and notify on changes (the cron/launchd entry)
    daemon             run ``check`` in a loop in the foreground
    test-notify        send a test notification on every configured channel
    summary            print the exams currently published for your programme
    status             show what the last check saw
    install-launchd    install a macOS LaunchAgent to run ``check`` periodically
    uninstall-launchd  remove that LaunchAgent
"""

from __future__ import annotations

import argparse
import logging
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, launchd
from .config import (
    Config,
    ConfigError,
    Settings,
    default_config_path,
    load_config,
    render_default_config,
)
from .http import Fetcher, FetchError
from .notify import Notification, build_notifiers, send_all
from .state import load_state, save_state
from .watch import (
    CheckResult,
    check_target,
    format_summary,
    load_summary,
    utc_now,
)
from .xlsx import Schedule

log = logging.getLogger("sdu_exam_watch")


def main(argv: list[str] | None = None) -> int:
    """Program entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", 0), getattr(args, "quiet", False))

    handlers = {
        "init": cmd_init,
        "check": cmd_check,
        "daemon": cmd_daemon,
        "test-notify": cmd_test_notify,
        "summary": cmd_summary,
        "status": cmd_status,
        "install-launchd": cmd_install_launchd,
        "uninstall-launchd": cmd_uninstall_launchd,
    }
    try:
        return handlers[args.command](args)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive
        log.info("interrupted")
        return 130


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _common_options() -> argparse.ArgumentParser:
    """Options accepted both before and after the subcommand.

    ``default=SUPPRESS`` means an option only sets the attribute when actually
    provided, so a flag given before the subcommand is not clobbered by the
    subparser's default.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        default=argparse.SUPPRESS,
        help="path to config.toml (default: ./config.toml or ~/.config/...)",
    )
    common.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=argparse.SUPPRESS,
        help="increase log verbosity",
    )
    common.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS,
        help="only log errors",
    )
    return common


def _build_parser() -> argparse.ArgumentParser:
    common = _common_options()
    parser = argparse.ArgumentParser(
        prog="sdu-exam-watch",
        parents=[common],
        description=(
            "Watch SDU exam-schedule pages and get notified when a new or "
            "updated schedule is published."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser(
        "init", parents=[common], help="write a starter config.toml"
    )
    p_init.add_argument("--path", help="where to write the config (default ./config.toml)")
    p_init.add_argument("--topic", help="ntfy topic to use (default: random)")
    p_init.add_argument("--force", action="store_true", help="overwrite an existing file")
    p_init.add_argument(
        "--no-targets", action="store_true", help="write settings/notify only"
    )

    p_check = sub.add_parser(
        "check", parents=[common], help="run one check and notify on changes"
    )
    p_check.add_argument(
        "--dry-run", action="store_true", help="print notifications instead of sending"
    )
    p_check.add_argument(
        "--force-notify",
        action="store_true",
        help="notify even when nothing changed (for testing)",
    )

    p_daemon = sub.add_parser(
        "daemon", parents=[common], help="run checks in a foreground loop"
    )
    p_daemon.add_argument(
        "--interval-hours", type=float, default=None, help="override the config interval"
    )
    p_daemon.add_argument("--dry-run", action="store_true")

    p_test = sub.add_parser(
        "test-notify", parents=[common], help="send a test notification"
    )
    p_test.add_argument("--message", default=None, help="custom message body")

    sub.add_parser(
        "summary", parents=[common], help="print the exams currently published"
    )
    sub.add_parser("status", parents=[common], help="show the state of the last check")

    p_install = sub.add_parser(
        "install-launchd", parents=[common], help="install the macOS LaunchAgent"
    )
    p_install.add_argument(
        "--interval-hours", type=float, default=None, help="override the config interval"
    )
    sub.add_parser(
        "uninstall-launchd", parents=[common], help="remove the macOS LaunchAgent"
    )
    return parser


def _setup_logging(verbosity: int, quiet: bool = False) -> None:
    if quiet:
        level = logging.ERROR
    elif verbosity >= 2:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _load(args: argparse.Namespace) -> Config:
    configured = getattr(args, "config", None)
    path = Path(configured).expanduser() if configured else default_config_path()
    return load_config(path)


def _make_fetcher(config: Config) -> Fetcher:
    settings = config.settings
    return Fetcher(
        timeout=settings.timeout,
        user_agent=settings.user_agent,
        retries=settings.retries,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.path or "config.toml").expanduser()
    if path.exists() and not args.force:
        print(
            f"{path} already exists — refusing to overwrite (use --force)",
            file=sys.stderr,
        )
        return 1
    topic = args.topic or f"sdu-exam-{secrets.token_hex(4)}"
    path.write_text(
        render_default_config(topic, include_targets=not args.no_targets),
        encoding="utf-8",
    )
    print(f"Wrote {path}")
    print()
    print("Next steps:")
    print("  1. Install the free 'ntfy' app from the App Store.")
    print(f"  2. In the app, subscribe to the topic: {topic}")
    print(f"  3. Test it:     sdu-exam-watch --config {path} test-notify")
    print(f"  4. Prime state: sdu-exam-watch --config {path} check")
    print(f"  5. Schedule it: sdu-exam-watch --config {path} install-launchd")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config = _load(args)
    return _run_check(config, dry_run=args.dry_run, force_notify=args.force_notify)


def cmd_daemon(args: argparse.Namespace) -> int:
    config = _load(args)
    interval_hours = (
        args.interval_hours
        if args.interval_hours is not None
        else config.settings.interval_hours
    )
    interval = max(60.0, interval_hours * 3600)
    log.info("daemon started; checking every %.1f hours", interval / 3600)
    while True:
        try:
            _run_check(config, dry_run=args.dry_run, force_notify=False)
        except Exception as exc:  # noqa: BLE001 - the loop must survive anything
            log.error("check failed: %s", exc, exc_info=log.isEnabledFor(logging.DEBUG))
        log.info("sleeping %.1f hours", interval / 3600)
        time.sleep(interval)


def cmd_test_notify(args: argparse.Namespace) -> int:
    config = _load(args)
    notifiers = build_notifiers(config.notify)
    message = args.message or (
        "This is a test from sdu-exam-watch. If you can read this on your "
        "phone, your notification channel works."
    )
    note = Notification(
        title="✅ sdu-exam-watch test",
        message=message,
        priority=config.notify.priority,
        tags=("white_check_mark",),
    )
    errors = send_all(notifiers, note)
    if errors:
        for error in errors:
            print(f"FAILED: {error}", file=sys.stderr)
        return 1
    print(f"Sent a test notification on {len(notifiers)} channel(s).")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    config = _load(args)
    fetcher = _make_fetcher(config)
    status = 0
    for target in config.targets:
        print(f"== {target.name}")
        print(f"   {target.url}")
        try:
            result = check_target(target, config.settings, fetcher, previous=None)
        except FetchError as exc:
            print(f"   ERROR: {exc}", file=sys.stderr)
            status = 1
            continue
        schedule = load_summary(fetcher, result, config.settings)
        if schedule is None:
            print("   no schedule spreadsheet found (see target/summary settings)")
            continue
        if schedule.title:
            print(f"   {schedule.title}")
        print(f"   {len(schedule.exams)} exam(s) for {target.programmes or 'all programmes'}")
        print()
        print(format_summary(schedule, limit=10_000) or "   (none)")
    return status


def cmd_status(args: argparse.Namespace) -> int:
    config = _load(args)
    state = load_state(config.settings.state_file)
    targets = state.get("targets", {})
    if not targets:
        print(f"No state yet at {config.settings.state_file} — run 'check' first.")
        return 0
    for name, entry in sorted(targets.items()):
        print(f"== {name}")
        print(f"   url          : {entry.get('url', '')}")
        print(f"   last checked : {entry.get('last_checked', 'never')}")
        if entry.get("schedule_title"):
            print(f"   schedule     : {entry['schedule_title']}")
        exams = entry.get("exams") or []
        if exams:
            print(f"   exams cached : {len(exams)}")
        for url, artifact in sorted((entry.get("artifacts") or {}).items()):
            stamp = artifact.get("last_modified") or artifact.get("etag") or "?"
            print(f"   - {url}\n       last-modified={stamp}")
        print()
    return 0


def cmd_install_launchd(args: argparse.Namespace) -> int:
    config = _load(args)
    interval_hours = (
        args.interval_hours
        if args.interval_hours is not None
        else config.settings.interval_hours
    )
    config_path = config.path or default_config_path()
    try:
        target = launchd.install(config_path, interval_hours)
    except RuntimeError as exc:
        print(f"could not install LaunchAgent: {exc}", file=sys.stderr)
        return 1
    print(f"Installed LaunchAgent: {target}")
    print(f"It will run 'check' every {interval_hours:g} hour(s).")
    print(f"Logs: {launchd.LOG_DIR}")
    return 0


def cmd_uninstall_launchd(args: argparse.Namespace) -> int:
    removed = launchd.uninstall()
    print("Removed LaunchAgent." if removed else "No LaunchAgent was installed.")
    return 0


# ---------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------


def _run_check(config: Config, *, dry_run: bool, force_notify: bool) -> int:
    settings = config.settings
    state = load_state(settings.state_file)
    fetcher = _make_fetcher(config)
    notifiers = build_notifiers(config.notify)

    problems = 0
    for target in config.targets:
        previous_entry = state.get("targets", {}).get(target.name, {})
        previous = previous_entry.get("artifacts", {})
        try:
            result = check_target(target, settings, fetcher, previous)
        except FetchError as exc:
            log.error("[%s] could not fetch %s: %s", target.name, target.url, exc)
            problems += 1
            continue

        for error in result.errors:
            log.warning("[%s] %s", target.name, error)
            problems += 1

        if result.baseline:
            log.info(
                "[%s] baseline recorded: %d artifact(s); silent on first run",
                target.name,
                len(result.artifacts),
            )
        elif not result.has_changes:
            log.info(
                "[%s] no changes (%d artifact(s))", target.name, len(result.artifacts)
            )
        else:
            _report_changes(result)

        should_notify = _should_notify(result, settings, force_notify)
        schedule = None
        if should_notify:
            schedule = load_summary(fetcher, result, settings)
            note = _build_notification(result, schedule, config, force_notify)
            if dry_run:
                print("\n--- DRY RUN: would send ---")
                print(f"Title: {note.title}")
                print(note.message)
                if note.attach:
                    print(f"Attach: {note.attachment_name or note.attach}")
                    print(f"        ({note.attach})")
                print("---")
            else:
                problems += len(send_all(notifiers, note))

        _persist_target(state, result, schedule, previous_entry)
        save_state(settings.state_file, state)

    return 1 if problems else 0


def _should_notify(
    result: CheckResult, settings: Settings, force_notify: bool
) -> bool:
    """Decide whether this check warrants a notification.

    The first check of a target only records a *baseline*: the schedule files
    are reported as "added" relative to empty state, which must not spam the
    user on installation. ``notify_on_first_run`` opts into that explicitly.
    """
    if force_notify:
        return True
    if result.baseline:
        return settings.notify_on_first_run
    return result.has_changes


def _report_changes(result: CheckResult) -> None:
    for url in result.added:
        log.info("[%s] NEW      %s", result.target.name, url)
    for url in result.changed:
        log.info("[%s] CHANGED  %s", result.target.name, url)
    for url in result.removed:
        log.warning("[%s] REMOVED  %s", result.target.name, url)


# Preference order when choosing which published file to attach.
_ATTACHMENT_SUFFIXES = (".pdf", ".xlsx", ".xlsm", ".xls")


def _pick_attachment(result: CheckResult) -> str:
    """Choose the file to attach: prefer the PDF, then the spreadsheet.

    Falls back to whatever is currently published when nothing changed (e.g.
    under ``--force-notify``) so the attachment is useful for testing too.
    """
    candidates = [*result.added, *result.changed]
    if not candidates:
        candidates = list(result.artifacts)
    for suffix in _ATTACHMENT_SUFFIXES:
        for url in candidates:
            if urlsplit(url).path.lower().endswith(suffix):
                return url
    return ""


def _attachment_name(schedule: Schedule | None, url: str) -> str:
    """Return a readable filename for the attached schedule."""
    suffix = Path(urlsplit(url).path).suffix or ".pdf"
    if schedule is not None and schedule.title:
        cleaned = re.sub(r"[^\w\s.\-]", "", schedule.title)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            return f"{cleaned}{suffix}"
    return urlsplit(url).path.rsplit("/", 1)[-1] or f"exam-schedule{suffix}"


def _build_notification(
    result: CheckResult,
    schedule: Schedule | None,
    config: Config,
    force_notify: bool,
) -> Notification:
    if result.added:
        title = "📅 New SDU exam schedule published"
    elif result.changed:
        title = "✏️ SDU exam schedule updated"
    elif result.removed:
        title = "⚠️ SDU exam schedule file removed"
    else:
        title = "🔔 sdu-exam-watch test"

    parts: list[str] = [result.target.name]
    if schedule is not None and schedule.title:
        parts.append(schedule.title)
    if schedule is not None and schedule.exams:
        summary = format_summary(schedule, config.settings.summary_limit)
        parts.append(f"Your exams ({len(schedule.exams)}):\n{summary}")
    elif result.target.programmes:
        parts.append(
            "No exams matched "
            + ", ".join(result.target.programmes)
            + " in the published file."
        )
    if force_notify and not result.has_changes:
        parts.append("(forced notification — nothing actually changed)")

    files = sorted({*result.added, *result.changed, *result.removed})
    if files:
        shown = "\n".join(f"• {url}" for url in files[:5])
        parts.append(f"Files:\n{shown}")

    attach = ""
    attachment_name = ""
    if config.notify.attach_files:
        attach = _pick_attachment(result)
        if attach:
            attachment_name = _attachment_name(schedule, attach)

    return Notification(
        title=title,
        message="\n\n".join(parts),
        priority=config.notify.priority,
        tags=config.notify.tags,
        click=result.page_url,
        attach=attach,
        attachment_name=attachment_name,
    )


def _persist_target(state, result: CheckResult, schedule, previous_entry) -> None:
    entry = {
        "url": result.target.url,
        "last_checked": utc_now(),
        "artifacts": {url: art.to_dict() for url, art in result.artifacts.items()},
        "schedule_title": previous_entry.get("schedule_title", ""),
        "exams": previous_entry.get("exams", []),
    }
    if schedule is not None:
        entry["schedule_title"] = schedule.title
        entry["exams"] = [exam.to_dict() for exam in schedule.exams]
    state.setdefault("targets", {})[result.target.name] = entry
