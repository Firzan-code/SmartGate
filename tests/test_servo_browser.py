"""Actual loopback Flask/Chrome exercise with fake camera and no actuator."""
import os
from pathlib import Path
import threading
import unittest


class ServoBrowserTests(unittest.TestCase):
    def test_counter_event_mobile_and_disconnect(self):
        from run_servo_demo import create_app
        from smart_gate_full.backend.servo_demo import ServoController
        from playwright.sync_api import sync_playwright, expect
        from werkzeug.serving import make_server
        class Camera:
            def get_state(self):
                return {'face_detected': True, 'left_eye_state': 'TERBUKA', 'right_eye_state': 'TERBUKA'}
            def get_jpeg_frame(self):
                return None
        controller = ServoController()
        state = Camera().get_state()
        for i in range(51):
            controller.on_frame(state, i / 10, now=i / 10)
        server = make_server('127.0.0.1', 0, create_app(controller, Camera()), threaded=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with sync_playwright() as driver:
                chrome = Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe'
                browser = driver.chromium.launch(executable_path=str(chrome), headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1200, 'height': 850})
                    page.route('**/video_feed', lambda route: route.abort())
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    response = page.goto(f'http://127.0.0.1:{server.server_port}')
                    self.assertEqual(response.headers['cache-control'], 'no-store')
                    expect(page.locator('#elapsed')).to_have_text('5.0 / 5 s')
                    self.assertEqual(page.locator('#event').inner_text(), 'SIMULASI: EVENT BUKA SEKALI')
                    self.assertEqual(page.locator('#mode').inner_text(), 'SIMULASI TANPA GERAK')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.route('**/api/state', lambda route: route.abort())
                    expect(page.locator('#mode')).to_have_text('KONEKSI DASHBOARD TERPUTUS')
                    self.assertEqual(page.locator('#elapsed').inner_text(), '—')
                    self.assertFalse(errors, errors)
                finally:
                    browser.close()
        finally:
            server.shutdown()
            worker.join(2)
            server.server_close()
        self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
