#!/usr/bin/env python3
"""Fetch the Central Canteen's current ISO week from the rendered JTK Blazor page."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

SOURCE = 'https://jtkmenu.torvekoekken.dk/86'
CANTEEN = '701'
ZONE = ZoneInfo('Europe/Copenhagen')
ROOT = Path(__file__).resolve().parent.parent


class Element:
    def __init__(self, tag='', attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def has_class(self, name):
        return name in (self.attrs.get('class') or '').split()

    def text(self):
        return ' '.join(''.join(c.text() if isinstance(c, Element) else c for c in self.children).split())


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Element()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs)
        self.stack[-1].children.append(element)
        if tag not in self.VOID:
            self.stack.append(element)
        elif tag == 'br':
            self.stack[-1].children.append(' ')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_menu(html: str, expected_monday: date | None = None) -> dict:
    """Read only dated mobile cards: desktop cards repeat the same dishes."""
    doc = Document(html)
    days = {}
    for card in doc.root.walk():
        match = re.fullmatch(r'menu-(\d{4}-\d{2}-\d{2})', card.attrs.get('id') or '')
        if not match:
            continue
        day = date.fromisoformat(match[1])
        if expected_monday and not expected_monday <= day < expected_monday + timedelta(days=7):
            continue
        bodies = [e for e in card.walk() if e.has_class('menubody')]
        if len(bodies) != 1:
            raise ValueError(f'Missing or ambiguous menu body for {day}')
        body = bodies[0]
        sections, current, dishes = [], '', []

        def flush():
            if dishes:
                sections.append({'title': current, 'text': '\n\n'.join(dishes)})
                dishes.clear()

        hours = ''
        for element in body.walk():
            if element.has_class('text-end'):
                h = re.search(r'\b(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})\b', element.text())
                if h:
                    hours = f'{h[1]} – {h[2]}'
            if element.has_class('menu_header_ny'):
                flush()
                current = element.text()
            elif element.has_class('menu_ret_ny') and element.text():
                dishes.append(element.text())
            elif element.has_class('menu_ret_detaljer') and element.text():
                if dishes:
                    dishes[-1] += '\n' + element.text()
                else:
                    dishes.append(element.text())
        flush()
        note = ' '.join(e.text() for e in body.walk() if e.tag == 'p') if not sections else ''
        if day.isoformat() in days:
            raise ValueError(f'Duplicate dated card for {day}')
        days[day.isoformat()] = {'date': day.isoformat(), 'hours': hours, 'sections': sections, 'note': note}
    if not days:
        raise ValueError('No dated menu cards found for the requested week')
    first = date.fromisoformat(min(days))
    monday = expected_monday or first - timedelta(days=first.weekday())
    weekdays = {(monday + timedelta(days=i)).isoformat() for i in range(5)}
    if not weekdays.issubset(days):
        raise ValueError('Incomplete menu: one or more weekday cards are missing')
    if any(not monday <= date.fromisoformat(d) < monday + timedelta(days=7) for d in days):
        raise ValueError('Menu contains mixed weeks')
    if not any(d['sections'] for d in days.values()):
        raise ValueError('No dishes published for the requested week')
    return {
        'source': SOURCE, 'canteen': 'The Central Canteen', 'canteenId': CANTEEN,
        'weekStart': monday.isoformat(), 'days': [days[k] for k in sorted(days)],
    }


def fetch_rendered(monday: date) -> str:
    # Blazor Server builds its menu through a SignalR circuit; urllib cannot select a week.
    from playwright.sync_api import sync_playwright
    year, week, _ = monday.isocalendar()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get('CANTEEN_BROWSER_PATH'))
        try:
            page = browser.new_page(locale='en-GB')
            page.set_default_timeout(45000)
            page.goto(SOURCE, wait_until='domcontentloaded', timeout=60000)
            selects = page.locator('select.form-select')
            selects.nth(2).wait_for()
            # Wait for Blazor's circuit, then select each control in order. Repeating the
            # complete selection below tolerates a handler resetting the other controls.
            page.wait_for_function("() => !!window.Blazor")
            for attempt in range(3):
                selects.nth(0).select_option(CANTEEN)
                selects.nth(1).select_option(str(year))
                selects.nth(2).select_option(str(week))
                try:
                    page.wait_for_function("""([canteen, year, week, monday]) => {
                        const s = [...document.querySelectorAll('select.form-select')];
                        const body = document.querySelector('#menu-' + monday + ' .menubody');
                        const heading = document.querySelector('#locationName')?.textContent || '';
                        return s[0]?.value === canteen && s[1]?.value === year && s[2]?.value === week
                            && body && /The Central Canteen/i.test(body.textContent)
                            && heading.includes(year) && new RegExp('\\\\b' + week + '\\\\b').test(heading);
                    }""", arg=[CANTEEN, str(year), str(week), monday.isoformat()], timeout=15000)
                    # Confirm every required weekday card before extracting the rendered DOM.
                    for i in range(5):
                        page.locator('#menu-' + (monday + timedelta(days=i)).isoformat() + ' .menubody').wait_for(state='attached')
                    # Dates and opening hours can render before the async dishes arrive.
                    # Do not mistake that intermediate Blazor render for an empty menu.
                    page.wait_for_function("""() => [...document.querySelectorAll('[id^="menu-"] .menubody .menu_ret_ny')]
                        .some(e => e.textContent.trim())""", timeout=30000)
                    rendered = page.content()
                    parse_menu(rendered, monday)
                    return rendered
                except Exception:
                    if attempt == 2:
                        bodies = page.locator('[id^="menu-"] .menubody')
                        preview = bodies.first.inner_html()[:1800] if bodies.count() else '(no dated menu bodies)'
                        print(f'warning: source menu body preview: {preview}', file=sys.stderr)
                        raise
            raise RuntimeError('Menu selection failed')
        finally:
            browser.close()


def fallback_menu(paths, monday):
    candidates = []
    for path in paths:
        if not path:
            continue
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            start = date.fromisoformat(data['weekStart'])
            datetime.fromisoformat(data['generatedAt'])
            if start.weekday() != 0 or start > monday or data.get('canteenId') != CANTEEN:
                continue
            days = data['days']
            dates = {d['date'] for d in days}
            if not {(start + timedelta(days=i)).isoformat() for i in range(5)}.issubset(dates):
                continue
            if not all(start <= date.fromisoformat(d['date']) < start + timedelta(days=7)
                       and isinstance(d['sections'], list)
                       and all(isinstance(s['text'], str) and isinstance(s['title'], str) for s in d['sections'])
                       for d in days):
                continue
            if not any(d['sections'] for d in days):
                continue
            candidates.append(data)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not candidates:
        raise ValueError('No usable previous or seed menu')
    data = max(candidates, key=lambda d: (d['weekStart'], d['generatedAt']))
    data['fetchFailed'] = True
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default=str(ROOT / 'data' / 'menu.json'))
    ap.add_argument('--previous', help='Published JSON to keep if the source fails')
    ap.add_argument('--seed', help='Initial saved-source JSON fallback')
    ap.add_argument('--html', help='Parse a saved rendered page instead of contacting the source')
    ap.add_argument('--week', help='ISO week, YYYY-Www; defaults to this week in Denmark')
    args = ap.parse_args(argv)
    try:
        if args.week:
            year, week = args.week.split('-W')
            monday = date.fromisocalendar(int(year), int(week), 1)
        else:
            today = datetime.now(ZONE).date()
            monday = today - timedelta(days=today.weekday())
        try:
            html = Path(args.html).read_text(encoding='utf-8') if args.html else fetch_rendered(monday)
            data = parse_menu(html, monday)
            data['generatedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            data['acquisition'] = 'saved-source' if args.html else 'live'
        except Exception as exc:
            print(f'warning: could not refresh source: {exc}', file=sys.stderr)
            data = fallback_menu([args.previous, args.seed], monday)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        temporary = out.with_suffix(out.suffix + '.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(out)
    except Exception as exc:
        print(f'error: menu fetch failed: {exc}', file=sys.stderr)
        return 1
    print(f'Wrote {len(data["days"])} days for {data["weekStart"]} to {out}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
