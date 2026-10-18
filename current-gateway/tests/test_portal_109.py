"""Host-only Portal integration checks; no physical device validation."""
import hashlib
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

from flask import render_template
from gateway.app import create_app
from gateway.config import Config
from gateway.simulator import Simulator

ROOT = Path(__file__).resolve().parents[1]
TRACKS = {
 'straight':'c318dd21a7dde2e4b7cd42a2ebebbb39a099d5ed9d8b3d4c35e5c14aa2b43c81',
 'wide-straight':'dea15f83cd651c23059808b674aba8902bd6dc510e734122f996fdd6a97b4b20',
 'curve':'61060b15703fed04b9333320957a1e37d18460bf9de54cf55d1435460befe6b6',
 'wide-curve':'976858739da9aeb9b3a4a14fe5f720a1d27e9b7f8af5b6a2a4c3d0160646e5a6',
 'challenge':'8131e0c7bdf9277662b1a07923e4ad23869c5f10c25f7bf797ca28c1e85e2c14',
 'wide-challenge':'739714214f64dfcca1efbaad1bacb4ab0719baf406f3ddcbe5853a15d87b609b',
 'circle':'3814c261ccbf842d10d7ca23cdf7be492f59302e1df3c29c8a571de7e67d5033',
 'wide-circle':'e79e28bf1ce76c2320568f8b773180ffb1cd1d638bf169507fd633daea3c507e',
 'oval':'ccb090bb0a783fdca1a520015ff26c8f3c63a85b43221fc92e216d3a5f271b1f',
 'elliptical':'7ea91db1b5d8a16bdc405fa536c9d2ab0a56d5424cd820e8045d785418975043',
 'infinity':'3fd0417f65b45f41db3640e3818713ea102753db220d8c64d781fb30134152ce',
 'wide-infinity':'c809d9656c01a754126beb3086ab577bd9777e57dae451c1ddbe4d90c219ee9c',
}


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class Portal109Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(data_dir=Path(self.tmp.name), admin_token='2'*64,
                          device_key='3'*64, mode='simulator')
        self.app = create_app(self.cfg, Simulator())
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions['ledger'].db.close()
        self.tmp.cleanup()

    def login(self):
        response = self.client.post('/api/admin/session', json={}, headers={
            'Origin':'http://localhost', 'X-Sentinel-Token':self.cfg.admin_token})
        self.assertEqual(response.status_code, 200)

    def test_major_pages_and_all_local_assets_resolve_with_self_hosted_content(self):
        self.login()
        for url in ['/', '/about', '/experiments', '/experiments/led-flasher',
                    '/experiments/autonomous-car', '/experiments/autonomous-car/gallery',
                    '/admin', '/display', '/display?view=twin', '/contact']:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                elements = Elements(html).elements
                self.assertIn('script-src \'self\'', response.headers['Content-Security-Policy'])
                self.assertNotIn('parent.SIM', html)
                self.assertNotIn('standalone-simulation', html)
                for tag, attrs in elements:
                    self.assertNotIn(tag, ('style',))
                    self.assertFalse(any(k.startswith('on') for k in attrs))
                    self.assertNotIn('style', attrs)
                    if tag == 'script': self.assertTrue(attrs.get('src', '').startswith('/static/'))
                    path = attrs.get('src') if tag in ('script', 'img') else attrs.get('href') if tag == 'link' else None
                    if path and path.startswith('/static/'):
                        asset = self.client.get(path)
                        self.assertEqual(asset.status_code, 200, (url, path))
                        asset.close()
                response.close()

    def test_navigation_preserves_routes_and_does_not_grant_admin(self):
        login = self.client.get('/admin/login')
        self.assertEqual(login.status_code, 200)
        self.assertIn('id="admin-credential"', login.get_data(as_text=True))
        html = self.client.get('/').get_data(as_text=True)
        links = {a.get('href') for tag,a in Elements(html).elements if tag == 'a'}
        for url in ['/', '/display', '/experiments', '/about', '/admin', '/contact']:
            self.assertIn(url, links)
        self.client.get('/experiments/autonomous-car/gallery')  # workstation session only
        admin = self.client.get('/admin')
        self.assertEqual(admin.status_code, 302)
        self.assertTrue(admin.headers['Location'].endswith('/admin/login'))
        denied = self.client.post('/api/admin/recovery', json={'action':'UNLOCK'},
                                  headers={'Origin':'http://localhost'})
        self.assertEqual(denied.status_code, 401)

    def test_authenticated_admin_template_keeps_live_csrf_and_session_expiry(self):
        self.login()
        html = self.client.get('/admin').get_data(as_text=True)
        csrf = next(a['content'] for t,a in Elements(html).elements
                    if t == 'meta' and a.get('name') == 'sentinel-csrf')
        self.assertRegex(csrf, r'^[0-9a-f]+$')
        self.assertIn('Session expires after 20 minutes.', html)
        self.assertIn('id="esp32-wrover-rtt"', html)
        bad = self.client.post('/api/admin/recovery', json={'action':'UNLOCK'},
                               headers={'Origin':'http://localhost'})
        self.assertEqual(bad.status_code, 401)

    def test_dynamic_gallery_keeps_capture_metadata_instead_of_mock_images(self):
        capture = {'url':'/api/experiments/autonomous-car/snapshot/'+'a'*32,
                   'length':1234, 'sha256':'b'*64, 'age_seconds':75}
        with self.app.test_request_context('/'):
            html = render_template('experiment_car_gallery.html', captures=[capture])
        self.assertIn(capture['url'], html)
        self.assertIn('1234 bytes', html)
        self.assertIn('b'*12, html)
        self.assertIn('Captured 1 minutes ago', html)
        self.assertNotIn('No recent captures', html)

    def test_production_feedback_and_diagnostic_limits_are_visible(self):
        led = Elements(self.client.get('/experiments/led-flasher').get_data(as_text=True)).elements
        for identifier in ('custom-result', 'custom-status'):
            attrs = next(a for _,a in led if a.get('id') == identifier)
            self.assertNotIn('hidden', attrs)
        car = self.client.get('/experiments/autonomous-car').get_data(as_text=True)
        attrs = next(a for _,a in Elements(car).elements if a.get('id') == 'car-result')
        self.assertNotIn('hidden', attrs)
        self.assertIn('Autonomous track following has not been physically validated.', car)

    def test_twelve_tracks_have_exact_phase2_normalized_svg_geometry(self):
        catalog = self.client.get('/api/display/tracks').json['tracks']
        self.assertEqual([x['id'] for x in catalog], list(TRACKS))
        macro = self.app.jinja_env.get_template('_tracks.html').module.track_svg
        for identifier, expected in TRACKS.items():
            with self.subTest(track=identifier):
                element = ET.fromstring(macro(identifier))
                def normalize(node):
                    self.assertNotIn('style', node.attrib)
                    if node.text: node.text = ' '.join(node.text.split())
                    if node.tail: node.tail = ' '.join(node.tail.split())
                    node.attrib = dict(sorted(node.attrib.items()))
                    for child in node: normalize(child)
                normalize(element)
                self.assertEqual(hashlib.sha256(ET.tostring(element, encoding='utf-8')).hexdigest(), expected)
                if identifier.startswith('wide-') or identifier == 'elliptical':
                    css = (ROOT/'gateway/static/style.css').read_text()
                    self.assertRegex(css, r'(?s)\.approved-track\[data-track="'+identifier+r'"\] \.track-line[^}]*stroke-width:\s*100px')
        display = self.client.get('/display').get_data(as_text=True)
        rendered = [a['data-track'] for t,a in Elements(display).elements
                    if t == 'svg' and a.get('class') == 'approved-track']
        self.assertEqual(set(rendered), set(TRACKS))
        self.assertEqual(len(rendered), 24)  # physical display and read-only twin


if __name__ == '__main__':
    unittest.main()
