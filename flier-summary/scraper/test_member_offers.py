"""Offline prototype checks. The HTML below is representative, not a live capture."""
import json
import tempfile
import unittest
from datetime import datetime
from email.message import Message
from pathlib import Path
from unittest import mock

import fetch_offers as fo
import member_offers as mo

NOW = datetime.fromisoformat('2026-11-15T12:00:00+00:00')
CARD = '''<article><span>Kun med Netto+ appen</span>
<img src="https://example.com/product.jpg"><h5>Yoggi yoghurt</h5>
<p>Ikke-medlemspris op til 12</p><p><strong>10</strong> .-</p>
<p>Udløber om 5 dage</p></article>'''


class NettoParserTest(unittest.TestCase):
    def test_offer_price_membership_and_expiry(self):
        offer, = mo.parse_netto_plus(CARD, NOW)
        self.assertEqual(offer['price'], 10)
        self.assertEqual(offer['nonMemberPrice'], 12)
        self.assertIsNone(offer['prePrice'])  # comparison price is not a historical price
        self.assertIsNone(offer['from'])  # do not invent the start date
        self.assertEqual(offer['till'], '2026-11-20T23:59:59+01:00')
        self.assertEqual(offer['membership'], 'Netto+')
        self.assertEqual(offer['sourceUrl'], mo.NETTO_PLUS_URL)
        self.assertEqual(offer['image'], 'https://example.com/product.jpg')
        self.assertIn('netto-plus:', offer['id'])

    def test_decimal_price_and_conditions(self):
        html = CARD.replace('<strong>10</strong> .-', '<strong>10</strong>,<sup>50</sup> -').replace('</h5>', '</h5><p>Max. 2 stk. 1 liter</p>')
        offer, = mo.parse_netto_plus(html, NOW)
        self.assertEqual(offer['price'], 10.5)
        self.assertIn('Max. 2 stk. 1 liter', offer['description'])

    def test_today_and_copenhagen_date(self):
        html = CARD.replace('om 5 dage', 'i dag')
        offer, = mo.parse_netto_plus(html, datetime.fromisoformat('2026-11-15T23:30:00+00:00'))
        self.assertEqual(offer['till'], '2026-11-16T23:59:59+01:00')

    def test_expiry_across_dst_change(self):
        offer, = mo.parse_netto_plus(CARD, datetime.fromisoformat('2026-03-26T12:00:00+00:00'))
        self.assertEqual(offer['till'], '2026-03-31T23:59:59+02:00')

    def test_repeated_markup_keeps_stable_id(self):
        one, = mo.parse_netto_plus(CARD, NOW)
        self.assertEqual(mo.parse_netto_plus(CARD + CARD, NOW), [one])
        self.assertEqual(mo.parse_netto_plus(CARD, NOW.replace(hour=20))[0]['id'], one['id'])

    def test_countdown_change_keeps_offer_id_stable(self):
        one, = mo.parse_netto_plus(CARD, NOW)
        next_day, = mo.parse_netto_plus(CARD.replace('om 5 dage', 'om 4 dage'), NOW.replace(day=16))
        self.assertEqual(next_day, one)

    def test_different_purchase_limits_are_not_overwritten(self):
        first = CARD.replace('</h5>', '</h5><p>Max 1 stk</p>')
        second = CARD.replace('</h5>', '</h5><p>Max 2 stk</p>')
        offers = mo.parse_netto_plus(first + second, NOW)
        self.assertEqual(len(offers), 2)
        self.assertNotEqual(offers[0]['id'], offers[1]['id'])

    def test_scripts_and_other_content_are_not_offers(self):
        html = '<script>' + CARD + '</script>'
        with self.assertRaises(RuntimeError):
            mo.parse_netto_plus(html, NOW)

    def test_changed_markup_or_partial_cards_rejects_whole_feed(self):
        for html in ('<html>Maintenance</html>', CARD.replace('Udløber om 5 dage', ''),
                     CARD + CARD.replace('<strong>10</strong> .-', '???'),
                     CARD + '<article>Kun med Netto+ appen<h5>Missing expiry</h5></article>'):
            with self.subTest(html=html), self.assertRaises(RuntimeError):
                mo.parse_netto_plus(html, NOW)

    def test_invalid_values_rejected(self):
        for html in (CARD.replace('<strong>10</strong>', '<strong>0</strong>'),
                     CARD.replace('<strong>10</strong>', '<strong>20</strong>'),
                     CARD.replace('om 5 dage', 'om 999 dage')):
            with self.subTest(html=html), self.assertRaises(RuntimeError):
                mo.parse_netto_plus(html, NOW)


class MemberFeedTest(unittest.TestCase):
    def test_failed_refresh_preserves_snapshot_and_timestamp_repeatedly(self):
        offer, = mo.parse_netto_plus(CARD, NOW)
        previous = {'memberFeeds': [{'key': 'netto-plus', 'fetchedAt': NOW.isoformat(), 'offers': [offer]}]}
        with mock.patch.object(fo, 'fetch_netto_plus', side_effect=RuntimeError('unavailable')):
            for _ in range(2):
                feed = fo.netto_member_feed(previous, '2026-11-16T12:00:00+00:00')
                self.assertEqual(feed['status'], 'cached')
                self.assertEqual(feed['fetchedAt'], NOW.isoformat())
                self.assertEqual(feed['offers'], [offer])
                previous = {'memberFeeds': [feed]}

    def test_failed_initial_refresh_is_unavailable(self):
        with mock.patch.object(fo, 'fetch_netto_plus', side_effect=RuntimeError('unavailable')):
            feed = fo.netto_member_feed({}, NOW.isoformat())
        self.assertEqual(feed['status'], 'unavailable')
        self.assertIsNone(feed['fetchedAt'])
        self.assertEqual(feed['offers'], [])

    def test_dedup_preserves_different_prices_memberships_and_conditions(self):
        member, = mo.parse_netto_plus(CARD, NOW)
        normal = dict(member, id='flier', membership=None)
        cheaper = dict(member, id='cheaper', price=8)
        other_pack = dict(member, id='pack', quantity='2 liter')
        limited = dict(member, id='limited', description='Max 1 stk')
        result = fo.merge_member_offers([normal], [member, member, cheaper, other_pack, limited])
        self.assertEqual([o['id'] for o in result], ['flier', member['id'], 'cheaper', 'pack', 'limited'])

    def test_member_feed_can_succeed_when_fliers_fail(self):
        member, = mo.parse_netto_plus(CARD, NOW)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(fo, 'resolve_dealers', return_value={}), \
                mock.patch.object(fo, 'fetch_netto_plus', return_value=[member]):
            output = Path(directory) / 'offers.json'
            self.assertEqual(fo.main(['--out', str(output), '--no-translate', '--netto-plus']), 0)
            data = json.loads(output.read_text())
        self.assertEqual(data['stores'][0]['count'], 1)
        self.assertEqual(data['memberFeeds'][0]['status'], 'ok')
        self.assertEqual(data['offers'][0]['cats'], ['dairy'])

    def test_failed_flier_source_does_not_reuse_outdated_member_snapshot(self):
        member, = mo.parse_netto_plus(CARD, NOW)
        old = {'stores': [{'key': 'netto'}], 'offers': [member], 'memberFeeds': []}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(fo, 'resolve_dealers', return_value={}), \
                mock.patch.object(fo, 'fetch_netto_plus', return_value=[dict(member, price=9)]):
            previous, output = Path(directory) / 'old.json', Path(directory) / 'offers.json'
            previous.write_text(json.dumps(old))
            self.assertEqual(fo.main(['--out', str(output), '--previous', str(previous), '--no-translate', '--netto-plus']), 0)
            data = json.loads(output.read_text())
        self.assertEqual(len(data['offers']), 1)
        self.assertEqual(data['offers'][0]['price'], 9)

    def test_failed_member_source_does_not_discard_new_flier_offers(self):
        member, = mo.parse_netto_plus(CARD, NOW)
        previous_data = {'stores': [], 'offers': [], 'memberFeeds': [{
            'key': 'netto-plus', 'fetchedAt': NOW.isoformat(), 'offers': [member],
        }]}
        raw = {'id': 'flier', 'heading': 'Mælk', 'pricing': {'price': 8}}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(fo, 'resolve_dealers', return_value={'netto': {'id': 'dealer'}}), \
                mock.patch.object(fo, 'fetch_dealer_offers', return_value=[raw]), \
                mock.patch.object(fo, 'fetch_netto_plus', side_effect=RuntimeError('offline')):
            previous, output = Path(directory) / 'old.json', Path(directory) / 'offers.json'
            previous.write_text(json.dumps(previous_data))
            self.assertEqual(fo.main(['--out', str(output), '--previous', str(previous), '--no-translate', '--netto-plus']), 0)
            data = json.loads(output.read_text())
        self.assertEqual(data['memberFeeds'][0]['status'], 'cached')
        self.assertEqual(data['memberFeeds'][0]['fetchedAt'], NOW.isoformat())
        self.assertEqual(data['stores'][0]['status'], 'ok')
        self.assertEqual(data['stores'][0]['count'], 2)
        self.assertEqual({o['id'] for o in data['offers']}, {'flier', member['id']})


class FetchTest(unittest.TestCase):
    def response(self, *, age='0', date='Sun, 15 Nov 2026 12:00:00 GMT', content_type='text/html; charset=utf-8'):
        response = mock.MagicMock()
        headers = Message()
        headers['Content-Type'] = content_type
        headers['Age'] = age
        headers['Date'] = date
        response.headers = headers
        response.read.return_value = CARD.encode()
        response.__enter__.return_value = response
        return response

    def test_reads_fresh_html_and_uses_fixed_public_url(self):
        with mock.patch.object(mo.urllib.request, 'urlopen', return_value=self.response()) as get:
            offer, = mo.fetch_netto_plus(NOW)
        self.assertEqual(offer['price'], 10)
        request = get.call_args.args[0]
        self.assertEqual(request.full_url, mo.NETTO_PLUS_URL)
        self.assertEqual(get.call_args.kwargs['timeout'], 30)

    def test_rejects_old_date_or_cache_crossing_local_midnight(self):
        cases = [self.response(date='Sat, 14 Nov 2026 12:00:00 GMT'),
                 self.response(age='50000'), self.response(age='-1')]
        for response in cases:
            with self.subTest(headers=response.headers), \
                    mock.patch.object(mo.urllib.request, 'urlopen', return_value=response), \
                    self.assertRaisesRegex(RuntimeError, 'too old'):
                mo.fetch_netto_plus(NOW)

    def test_rejects_non_html_and_bad_headers(self):
        for response in (self.response(content_type='application/json'), self.response(age='unknown'), self.response(date='unknown'),
                         self.response(date='Sun, 15 Nov 2026 12:00:00 -0000')):
            with self.subTest(headers=response.headers), \
                    mock.patch.object(mo.urllib.request, 'urlopen', return_value=response), \
                    self.assertRaises(RuntimeError):
                mo.fetch_netto_plus(NOW)


if __name__ == '__main__':
    unittest.main()
