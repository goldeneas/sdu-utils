"""Access diagnostics must preserve evidence without creating a publishable feed."""
import hashlib
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import member_offers as mo
import probe_member_sources as probe
import test_member_offers as fixtures


class CaptureTest(unittest.TestCase):
    def run_probe(self, directory, sources):
        with mock.patch.object(probe, 'SOURCES', sources), mock.patch.object(probe, 'datetime') as clock:
            clock.now.return_value = fixtures.NOW
            return probe.main(['--out-dir', str(directory)])

    def test_capture_keeps_markup_and_safe_headers_but_not_session_headers(self):
        response = fixtures.FetchTest().response()
        response.headers['Set-Cookie'] = 'session=do-not-retain'
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(mo.urllib.request, 'urlopen', return_value=response) as get:
            directory = Path(tmp) / 'capture'
            self.assertEqual(self.run_probe(directory, [('netto-plus', mo.NETTO_PLUS_URL)]), 0)
            source, = json.loads((directory / 'report.json').read_text())['sources']
            captured = (directory / source['html']).read_bytes()
            self.assertEqual(captured, fixtures.CARD.encode())
            self.assertEqual(source['sha256'], hashlib.sha256(captured).hexdigest())
            self.assertEqual(source['nettoValidation'], {'status': 'ok', 'offerCount': 1})
            self.assertNotIn('Set-Cookie', source['headers'])
            self.assertNotIn('Cookie', get.call_args.args[0].headers)
            self.assertNotIn('offers', source)
            self.assertFalse((directory / 'offers.json').exists())

    def test_proxy_denial_is_not_an_origin_403_and_does_not_stop_other_sources(self):
        denied = urllib.error.URLError(OSError('Tunnel connection failed: 403 Forbidden'))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(mo.urllib.request, 'urlopen', side_effect=[denied, fixtures.FetchTest().response()]):
            directory = Path(tmp) / 'capture'
            self.assertEqual(self.run_probe(directory, [('netto-plus', mo.NETTO_PLUS_URL), ('bilka-plus', 'https://www.bilka.dk/plus/')]), 1)
            failed, accessible = json.loads((directory / 'report.json').read_text())['sources']
            self.assertEqual(failed['status'], 'proxy-denied')
            self.assertNotIn('httpStatus', failed)
            self.assertFalse((directory / 'netto-plus.html').exists())
            self.assertEqual(accessible['status'], 'ok')
            self.assertNotIn('nettoValidation', accessible)

    def test_origin_denial_is_reported_separately(self):
        denied = urllib.error.HTTPError(mo.NETTO_PLUS_URL, 403, 'Forbidden', {}, None)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mo.urllib.request, 'urlopen', side_effect=denied):
            directory = Path(tmp) / 'capture'
            self.assertEqual(self.run_probe(directory, [('netto-plus', mo.NETTO_PLUS_URL)]), 1)
            source, = json.loads((directory / 'report.json').read_text())['sources']
            self.assertEqual(source['status'], 'http-error')
            self.assertEqual(source['httpStatus'], 403)

    def test_accessible_but_changed_html_is_retained_and_validation_fails(self):
        response = fixtures.FetchTest().response()
        response.read.return_value = b'<html><body>Maintenance</body></html>'
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mo.urllib.request, 'urlopen', return_value=response):
            directory = Path(tmp) / 'capture'
            self.assertEqual(self.run_probe(directory, [('netto-plus', mo.NETTO_PLUS_URL)]), 1)
            source, = json.loads((directory / 'report.json').read_text())['sources']
            self.assertEqual(source['status'], 'ok')
            self.assertEqual(source['nettoValidation']['status'], 'error')
            self.assertEqual((directory / source['html']).read_bytes(), response.read.return_value)

    def test_stale_page_is_retained_without_claiming_a_valid_countdown(self):
        response = fixtures.FetchTest().response(date='Sat, 14 Nov 2026 12:00:00 GMT')
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mo.urllib.request, 'urlopen', return_value=response):
            directory = Path(tmp) / 'capture'
            self.assertEqual(self.run_probe(directory, [('netto-plus', mo.NETTO_PLUS_URL)]), 1)
            source, = json.loads((directory / 'report.json').read_text())['sources']
            self.assertTrue((directory / source['html']).exists())
            self.assertEqual(source['nettoValidation']['status'], 'error')
            self.assertNotIn('offerCount', source['nettoValidation'])

    def test_capture_requires_a_new_directory_so_old_html_cannot_look_fresh(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(probe, 'fetch_public_html') as get, \
                mock.patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                probe.main(['--out-dir', tmp])
            get.assert_not_called()

    def test_empty_oversized_and_non_html_responses_are_not_captures(self):
        empty = fixtures.FetchTest().response()
        empty.read.return_value = b''
        oversized = fixtures.FetchTest().response()
        oversized.read.return_value = b'x' * (mo.MAX_PAGE_BYTES + 1)
        non_html = fixtures.FetchTest().response(content_type='application/json')
        for response in (empty, oversized, non_html):
            with self.subTest(headers=response.headers), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(mo.urllib.request, 'urlopen', return_value=response):
                directory = Path(tmp) / 'capture'
                self.assertEqual(self.run_probe(directory, [('netto-plus', mo.NETTO_PLUS_URL)]), 1)
                self.assertEqual(list(directory.glob('*.html')), [])


if __name__ == '__main__':
    unittest.main()
