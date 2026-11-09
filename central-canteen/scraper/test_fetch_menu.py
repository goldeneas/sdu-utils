import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fetch_menu as fm

FIXTURE = Path(__file__).parent / 'fixtures' / 'week-2026-46.html'


class MenuTests(unittest.TestCase):
    def test_real_uploaded_source_without_desktop_duplicates(self):
        menu = fm.parse_menu(FIXTURE.read_text(), date(2026, 11, 9))
        self.assertEqual(menu['canteenId'], '701')
        self.assertEqual(menu['weekStart'], '2026-11-09')
        self.assertEqual(len(menu['days']), 6)
        monday = menu['days'][0]
        self.assertEqual(monday['hours'], '07:45 – 18:00')
        self.assertEqual(monday['sections'], [{'title': 'Varme retter', 'text': 'Paprika stew with beans\n\nPaprika stew with turkey'}])
        self.assertEqual(menu['days'][-1]['sections'], [])
        self.assertEqual(menu['days'][-1]['note'], 'Menu endnu ikke planlagt.')
        self.assertEqual(menu['days'][-1]['hours'], '09:00 – 13:30')

    def test_wrong_week_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'No dated'):
            fm.parse_menu(FIXTURE.read_text(), date(2026, 11, 16))

    def test_partial_week_is_rejected(self):
        html = FIXTURE.read_text().replace('id="menu-2026-11-10"', 'id="removed"')
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            fm.parse_menu(html, date(2026, 11, 9))

    def test_empty_unrendered_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'No dated'):
            fm.parse_menu('<html><script src="blazor.server.js"></script></html>')

    def test_dish_details_and_multiple_categories(self):
        html = FIXTURE.read_text().replace('Paprika stew with beans', 'Beans &amp; lentils')
        target = '<div class="menu_ret_detaljer"></div><div class="menu_ret_ny">Paprika stew with turkey'
        html = html.replace(target, '<div class="menu_ret_detaljer">Contains <strong>milk</strong></div><div class="menu_header_ny">Second category</div><div class="menu_ret_ny">Paprika stew with turkey')
        sections = fm.parse_menu(html)['days'][0]['sections']
        self.assertEqual(sections[0]['text'], 'Beans & lentils\nContains milk')
        self.assertEqual(sections[1]['title'], 'Second category')

    def test_main_preserves_existing_file_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'menu.json'
            out.write_text('previous menu')
            with patch.object(fm, 'fetch_rendered', side_effect=RuntimeError('offline')):
                self.assertEqual(fm.main(['--out', str(out)]), 1)
            self.assertEqual(out.read_text(), 'previous menu')

    def test_snapshot_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'menu.json'
            self.assertEqual(fm.main(['--html', str(FIXTURE), '--week', '2026-W46', '--out', str(out)]), 0)
            data = json.loads(out.read_text())
            self.assertEqual(data['acquisition'], 'saved-source')
            self.assertEqual(data['weekStart'], '2026-11-09')

    def test_iso_week_across_new_year(self):
        with tempfile.TemporaryDirectory() as d, patch.object(fm, 'fetch_rendered', side_effect=RuntimeError('offline')) as fetch:
            fm.main(['--week', '2026-W01', '--out', str(Path(d) / 'menu.json')])
            fetch.assert_called_once_with(date(2025, 12, 29))

    def test_seed_fallback_preserves_actual_capture_date(self):
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / 'seed.json'
            data = fm.parse_menu(FIXTURE.read_text())
            data['generatedAt'] = '2026-11-09T06:00:00+00:00'
            seed.write_text(json.dumps(data))
            out = Path(d) / 'out.json'
            with patch.object(fm, 'fetch_rendered', side_effect=RuntimeError('offline')):
                self.assertEqual(fm.main(['--week', '2026-W47', '--seed', str(seed), '--out', str(out)]), 0)
            result = json.loads(out.read_text())
            self.assertEqual(result['generatedAt'], data['generatedAt'])
            self.assertEqual(result['weekStart'], '2026-11-09')
            self.assertTrue(result['fetchFailed'])

    def test_newer_previous_menu_wins_over_seed(self):
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / 'seed.json'
            previous = Path(d) / 'previous.json'
            data = fm.parse_menu(FIXTURE.read_text())
            data['generatedAt'] = '2026-11-09T06:00:00+00:00'
            seed.write_text(json.dumps(data))
            data['generatedAt'] = '2026-11-10T06:00:00+00:00'
            previous.write_text(json.dumps(data))
            result = fm.fallback_menu([seed, previous], date(2026, 11, 9))
            self.assertEqual(result['generatedAt'], data['generatedAt'])

    def test_future_week_fallback_is_not_used(self):
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / 'seed.json'
            data = fm.parse_menu(FIXTURE.read_text())
            data['generatedAt'] = '2026-11-09T06:00:00+00:00'
            seed.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'No usable'):
                fm.fallback_menu([seed], date(2026, 11, 2))


if __name__ == '__main__':
    unittest.main()
