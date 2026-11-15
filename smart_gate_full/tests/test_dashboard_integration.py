"""Exercise the real Flask dashboard in Chrome without any physical devices."""
import importlib.util
from pathlib import Path
import os
import threading
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'Browser integration requires playwright')
class RealDashboardTests(unittest.TestCase):
    def test_actual_http_headers_waiting_api_and_browser(self):
        from playwright.sync_api import sync_playwright
        from smart_gate_full.backend.app import create_app
        from smart_gate_full.backend.runtime import MonitorRuntime
        from werkzeug.serving import make_server
        runtime = MonitorRuntime()  # no start: must not access camera/UDP/COM
        server = make_server('127.0.0.1', 0, create_app(runtime), threaded=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        errors = []
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as driver:
                chrome = Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe'
                browser = driver.chromium.launch(executable_path=str(chrome), headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1365, 'height': 900})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    response = page.goto(base)
                    self.assertEqual(response.status, 200)
                    self.assertIn('no-store', response.headers['cache-control'])
                    self.assertIn("connect-src 'self'", response.headers['content-security-policy'])
                    page.wait_for_function("document.getElementById('connection-status').textContent === 'API TERHUBUNG'")
                    self.assertEqual(page.locator('#audio-status').inner_text(), 'MENUNGGU')
                    self.assertEqual(page.locator('#vision-status').inner_text(), 'MENUNGGU')
                    self.assertEqual(page.locator('#siren-probability').inner_text(), '—')
                    self.assertTrue(page.locator('#camera-image').is_hidden())
                    payload = page.request.get(base + '/api/state').json()
                    self.assertEqual(page.locator('#serial-line').inner_text(), payload['serial_line'])
                    self.assertFalse(payload['authorized'])
                    self.assertIsNone(payload['audio']['siren_probability'])
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.locator('#pause-monitor').click()
                    self.assertEqual(page.locator('#connection-status').inner_text(), 'MONITOR DIJEDA')
                    self.assertEqual(page.locator('#serial-line').inner_text(), '—')
                    self.assertFalse(errors, errors)
                finally:
                    browser.close()
        finally:
            server.shutdown()
            worker.join(2)
            server.server_close()
            runtime.stop()
        self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
