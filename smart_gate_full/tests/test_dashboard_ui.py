"""Frontend contract checks only; no camera, serial port, or model is opened.

Run: python -m unittest discover -s smart_gate_full/tests -p test_dashboard_ui.py -v
"""
from html.parser import HTMLParser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import importlib.util
import json
import os
import threading
import unittest


DASHBOARD = Path(__file__).resolve().parents[1] / "backend" / "static_dashboard.html"


class DashboardMarkup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = {}
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if "id" in attrs:
            if attrs["id"] in self.ids:
                raise AssertionError(f"Duplicate id: {attrs['id']}")
            self.ids[attrs["id"]] = attrs


class DashboardUIContractTests(unittest.TestCase):
    def test_initial_view_waits_for_real_data(self):
        self.assertTrue(DASHBOARD.is_file(), "Missing static frontend artifact")
        text = DASHBOARD.read_text(encoding="utf-8")
        markup = DashboardMarkup(text)
        self.assertIn('<html lang="id">', text)
        for key in ("connection-status", "vision-status", "audio-status", "transport-status"):
            self.assertEqual(markup.ids[key]["data-state"], "waiting")
        for key in ("face-detected", "left-eye-state", "right-eye-state", "ear-avg",
                    "blink-counter", "total-blinks", "siren-detected", "siren-probability",
                    "serial-line", "spectrum", "event-log", "camera-image", "camera-placeholder"):
            self.assertIn(key, markup.ids)
        self.assertNotIn("src", markup.ids["camera-image"], "Do not open the camera before a live API state")
        self.assertIn("hidden", markup.ids["camera-image"])
        self.assertIn("MENUNGGU", text)
        self.assertFalse(any(attrs.get("data-state") == "live" for _, attrs in markup.tags))
        self.assertIn("MAX9814", text)
        self.assertIn("Audio Spectrogram Transformer (AST)", text)
        self.assertIn("akurasi pada mikrofon nyata belum tervalidasi", text)
        self.assertIn("bukan verifikasi identitas", text)

    def test_no_remote_dependencies_or_html_injection_sinks(self):
        text = DASHBOARD.read_text(encoding="utf-8")
        markup = DashboardMarkup(text)
        for tag, attrs in markup.tags:
            for attr in ("src", "href"):
                self.assertFalse(attrs.get(attr, "").startswith(("http:", "https:", "//")), (tag, attrs))
        for unsafe in (".innerHTML", "insertAdjacentHTML", "document.write", "getUserMedia", "navigator.serial"):
            self.assertNotIn(unsafe, text)
        self.assertEqual(sum(tag == "button" for tag, _ in markup.tags), 1,
                         "Only the explicitly labelled monitor pause action is allowed")
        self.assertEqual(markup.ids["authorized"]["data-authorized"], "false")


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Optional browser checks require playwright")
class DashboardBrowserTests(unittest.TestCase):
    """Explicit API fixtures, never a claim of physical microphone/camera validation."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        chrome = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"
        cls.browser = cls.driver.chromium.launch(executable_path=str(chrome), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 390, "height": 844})
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.state = {
            "vision": {"status": "live", "face_detected": True,
                       "left_eye_state": "TERBUKA", "right_eye_state": "TERTUTUP",
                       "eye_state": "TRANSISI", "ear_left": .31, "ear_right": .12,
                       "ear_avg": .215, "blink_counter": 2, "total_blinks": 7,
                       "liveness_verified": True, "fps": 18.5, "processing_ms": 12,
                       "error": None},
            "audio": {"status": "live", "siren_detected": True, "siren_probability": .92,
                      "consecutive_hits": 2, "source": "MAX9814_ESP32",
                      "spectrum_freqs_hz": [0, 500, 1000, 4000, 8000],
                      "spectrum_magnitudes": [0, .4, 1, .1, 0],
                      "inference_ms": 8.2, "adc_min": 100, "adc_max": 3000,
                      "adc_p2p": 2900, "adc_avg": 2047.5, "error": None},
            "transport": {"status": "live", "peer": "192.0.2.5:5007", "packets": 50,
                          "gaps": 1, "rejected": 2, "seconds_since_packet": .02,
                          "sample_rate_hz": 16000, "udp_port": 5006},
            "serial_line": "FIXTURE UJI: WAJAH=YA SIRENE=YA",
            "events": [{"time": "12:34:56", "message": "Fixture uji UI; bukan input perangkat"}],
            "authorized": False,
        }
        self.offline = False
        self.page.route("http://dashboard.test/", lambda route: route.fulfill(
            status=200, content_type="text/html", body=DASHBOARD.read_text(encoding="utf-8")))
        self.page.route("**/api/state", self.api_route)
        self.page.route("**/video_feed*", lambda route: route.fulfill(status=503, body="No real camera in UI tests"))

    def api_route(self, route):
        if self.offline:
            route.abort("connectionrefused")
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(self.state))

    def tearDown(self):
        self.page.close()

    def wait_for_text(self, element_id, expected):
        self.page.wait_for_function("([id, value]) => document.getElementById(id).textContent === value",
                                    arg=[element_id, expected], timeout=6000)

    def test_real_api_fields_render_without_null_coercion(self):
        self.page.goto("http://dashboard.test/")
        self.wait_for_text("siren-detected", "SIRENE")
        self.wait_for_text("left-eye-state", "TERBUKA")
        self.assertEqual(self.page.locator("#right-eye-state").inner_text(), "TERTUTUP")
        self.assertEqual(self.page.locator("#serial-line").inner_text(), self.state["serial_line"])
        self.assertEqual(self.page.locator("#total-blinks").inner_text(), "7")
        self.assertNotEqual(self.page.locator("#ear-avg").inner_text(), "—")
        self.assertTrue(self.page.locator("#spectrum-placeholder").is_hidden())
        self.assertTrue(self.page.evaluate("""() => {
            const c=document.getElementById('spectrum');
            const p=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
            return p.some((value,index) => index%4===3 && value>0);
        }"""), "The actual frequency canvas must contain a rendered plot")
        self.wait_for_text("camera-placeholder-title", "Video tidak tersedia")
        self.assertTrue(self.page.locator("#camera-image").is_hidden())
        self.assertEqual(self.page.locator("#camera-status").get_attribute("data-state"), "error")
        self.state["audio"]["siren_probability"] = None
        self.state["vision"]["ear_avg"] = None
        self.wait_for_text("siren-probability", "—")
        self.wait_for_text("ear-avg", "—")
        self.assertEqual(self.page.locator("#authorized").get_attribute("data-authorized"), "false")
        self.assertEqual(self.errors, [])

    def test_offline_invalidates_live_results_video_and_plot(self):
        self.page.goto("http://dashboard.test/")
        self.wait_for_text("siren-detected", "SIRENE")
        self.offline = True
        self.wait_for_text("connection-status", "OFFLINE")
        for field in ("siren-detected", "ear-avg", "serial-line", "adc-min", "packet-count"):
            self.assertEqual(self.page.locator("#" + field).inner_text(), "—", field)
        self.assertEqual(self.page.locator('[data-state="live"]').count(), 0)
        self.assertTrue(self.page.locator("#camera-image").is_hidden())
        self.assertIsNone(self.page.locator("#camera-image").get_attribute("src"))
        self.assertFalse(self.page.locator("#spectrum-placeholder").is_hidden())
        self.assertIn("historis", self.page.locator("#event-context").inner_text())
        self.assertEqual(self.errors, [])

    def test_pause_only_suspends_monitor_and_resumes_waiting_for_api(self):
        requests = []
        self.page.on("request", lambda request: requests.append((request.method, request.url)))
        self.page.goto("http://dashboard.test/")
        self.wait_for_text("siren-detected", "SIRENE")
        self.page.locator("#pause-monitor").click()
        self.wait_for_text("connection-status", "MONITOR DIJEDA")
        self.assertEqual(self.page.locator("#pause-monitor").get_attribute("aria-pressed"), "true")
        self.assertEqual(self.page.locator("#siren-detected").inner_text(), "—")
        count = sum(url.endswith("/api/state") for _, url in requests)
        self.page.wait_for_timeout(1200)
        self.assertEqual(sum(url.endswith("/api/state") for _, url in requests), count)
        self.assertTrue(all(method == "GET" for method, _ in requests))
        self.page.locator("#pause-monitor").click()
        self.wait_for_text("siren-detected", "SIRENE")
        self.assertEqual(self.page.locator("#pause-monitor").get_attribute("aria-pressed"), "false")
        self.assertEqual(self.errors, [])

    def test_waiting_buffering_and_errors_never_show_a_classification(self):
        self.state["vision"]["status"] = "waiting"
        self.state["audio"]["status"] = "buffering"
        self.page.goto("http://dashboard.test/")
        self.wait_for_text("audio-status", "MENGISI BUFFER")
        self.assertEqual(self.page.locator("#vision-status").get_attribute("data-state"), "waiting")
        for field in ("face-detected", "left-eye-state", "siren-detected", "siren-probability"):
            self.assertEqual(self.page.locator("#" + field).inner_text(), "—")
        self.assertIsNone(self.page.locator("#camera-image").get_attribute("src"))
        self.state["vision"]["status"] = "error"
        self.state["vision"]["error"] = "Fixture: kamera tidak tersedia"
        self.state["audio"]["status"] = "error"
        self.state["audio"]["error"] = "Fixture: inferensi gagal"
        self.wait_for_text("audio-status", "ERROR")
        self.wait_for_text("vision-error", self.state["vision"]["error"])
        self.wait_for_text("audio-error", self.state["audio"]["error"])
        self.assertEqual(self.page.locator("#adc-min").inner_text(), "—")
        self.assertEqual(self.errors, [])

    def test_unseen_face_clears_eyes_and_stale_transport_invalidates_audio(self):
        self.state["vision"]["face_detected"] = False
        self.state["transport"]["status"] = "stale"
        self.page.goto("http://dashboard.test/")
        self.wait_for_text("face-detected", "TIDAK")
        self.assertEqual(self.page.locator("#left-eye-state").inner_text(), "TIDAK TERDETEKSI")
        self.assertEqual(self.page.locator("#right-eye-state").inner_text(), "TIDAK TERDETEKSI")
        self.assertEqual(self.page.locator("#ear-avg").inner_text(), "—")
        self.assertEqual(self.page.locator("#audio-status").get_attribute("data-state"), "stale")
        self.assertEqual(self.page.locator("#siren-detected").inner_text(), "—")
        self.assertFalse(self.page.locator("#spectrum-placeholder").is_hidden())
        self.assertEqual(self.errors, [])

    def test_api_strings_are_inert_and_events_are_bounded(self):
        injection = '<img src=x onerror="window.apiInjected=true">'
        self.state["serial_line"] = injection
        self.state["transport"]["peer"] = injection
        self.state["events"] = [{"time": injection, "message": injection} for _ in range(45)]
        self.state["vision"]["error"] = injection
        self.state["authorized"] = True
        self.page.goto("http://dashboard.test/")
        self.wait_for_text("serial-line", injection)
        self.assertEqual(self.page.locator("#event-log li").count(), 30)
        self.assertEqual(self.page.locator("#event-count").inner_text(), "30 / 30")
        self.assertEqual(self.page.locator("#transport-peer").inner_text(), injection)
        self.assertEqual(self.page.locator("#vision-error").inner_text(), injection)
        self.assertEqual(self.page.locator("#serial-line img, #event-log img, #vision-error img").count(), 0)
        self.assertFalse(self.page.evaluate("Boolean(window.apiInjected)"))
        self.assertEqual(self.page.locator("#authorized").get_attribute("data-authorized"), "false")
        self.assertEqual(self.errors, [])

    def test_mobile_and_desktop_have_readable_metrics_without_overflow(self):
        self.page.goto("http://dashboard.test/")
        self.wait_for_text("siren-detected", "SIRENE")
        for width in (390, 1440):
            self.page.set_viewport_size({"width": width, "height": 900})
            for field in ("left-eye-state", "right-eye-state", "ear-avg", "siren-detected", "siren-probability"):
                self.assertTrue(self.page.locator("#" + field).is_visible())
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width)
            self.assertTrue(self.page.evaluate("""() => ['left-eye-state', 'right-eye-state', 'siren-detected', 'siren-probability']
                .every(id => {const e=document.getElementById(id);const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;})"""))
        self.assertEqual(self.errors, [])

    def test_long_state_labels_remain_inside_mobile_panels(self):
        self.state["audio"]["siren_detected"] = False
        self.state["vision"]["left_eye_state"] = "TIDAK_TERDETEKSI"
        self.state["vision"]["right_eye_state"] = "TIDAK_TERDETEKSI"
        self.page.goto("http://dashboard.test/")
        self.wait_for_text("siren-detected", "BUKAN SIRENE")
        for status in ("live", "offline"):
            if status == "offline":
                self.offline = True
                self.wait_for_text("connection-status", "OFFLINE")
            clipped = self.page.evaluate("""() => [...document.querySelectorAll('.panel-header,.eye-card,.siren-output,.metric,.connection-notice')]
                .filter(e=>e.scrollWidth>e.clientWidth+1)
                .map(e=>({className:e.className,width:e.clientWidth,content:e.scrollWidth}))""")
            self.assertEqual(clipped, [], status)
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        self.assertEqual(self.errors, [])

    def test_fetch_times_out_without_overlapping_requests(self):
        self.page.route("**/api/state", lambda route: None)
        requests = []
        self.page.on("request", lambda request: requests.append(request.url) if request.url.endswith("/api/state") else None)
        self.page.goto("http://dashboard.test/")
        self.page.wait_for_timeout(1700)
        self.assertEqual(len(requests), 1, "A slow request must not overlap another poll")
        self.wait_for_text("connection-status", "OFFLINE")
        self.assertIn("batas waktu", self.page.locator("#connection-message").inner_text())
        self.assertEqual(self.page.locator("#face-detected").inner_text(), "—")
        self.assertEqual(self.page.locator('[data-state="live"]').count(), 0)
        self.assertEqual(self.errors, [])

    def test_malformed_json_and_invalid_numbers_are_not_healthy_results(self):
        self.state["vision"]["ear_avg"] = "NaN"
        self.state["vision"]["ear_left"] = None
        self.state["audio"]["siren_probability"] = 1.2
        self.state["audio"]["inference_ms"] = "Infinity"
        self.page.goto("http://dashboard.test/")
        self.wait_for_text("siren-detected", "SIRENE")
        for field in ("ear-avg", "ear-left", "siren-probability", "audio-inference"):
            self.assertEqual(self.page.locator("#" + field).inner_text(), "—", field)
        self.state["audio"]["source"] = "LAPTOP_MICROPHONE"
        self.wait_for_text("audio-status", "ERROR")
        self.assertEqual(self.page.locator("#siren-detected").inner_text(), "—")
        self.assertIn("MAX9814_ESP32", self.page.locator("#audio-error").inner_text())
        self.page.route("**/api/state", lambda route: route.fulfill(
            status=200, content_type="application/json", body="{invalid-json"))
        self.wait_for_text("connection-status", "OFFLINE")
        self.assertEqual(self.page.locator('[data-state="live"]').count(), 0)
        self.assertEqual(self.errors, [])

    def test_file_mode_stays_offline_without_network_or_capture_access(self):
        self.page.goto(DASHBOARD.as_uri())
        self.wait_for_text("connection-status", "BUKA MELALUI BACKEND")
        self.assertEqual(self.page.locator("#vision-status").get_attribute("data-state"), "waiting")
        self.assertEqual(self.page.locator("#siren-detected").inner_text(), "—")
        self.assertIsNone(self.page.locator("#camera-image").get_attribute("src"))
        self.assertEqual(self.errors, [])

    def test_mjpeg_first_frame_displays_before_stream_closes(self):
        # Generate a visibly non-camera JPEG fixture, never access a capture device.
        data_url = self.page.evaluate("""() => {
            const c = document.createElement('canvas'); c.width = 32; c.height = 18;
            const x = c.getContext('2d'); x.fillStyle = '#9a9bff'; x.fillRect(0, 0, 32, 18);
            return c.toDataURL('image/jpeg');
        }""")
        jpeg = base64.b64decode(data_url.split(",", 1)[1])
        fixture = self.state
        stop = threading.Event()
        stream_started = threading.Event()

        class FixtureHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(handler):
                if handler.path.startswith("/video_feed"):
                    handler.send_response(200)
                    handler.send_header("Content-Type", "multipart/x-mixed-replace; boundary=ui-fixture")
                    handler.end_headers()
                    try:
                        while not stop.is_set():
                            handler.wfile.write(b"--ui-fixture\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                                + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                            handler.wfile.flush()
                            stream_started.set()
                            stop.wait(.15)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        pass
                    return
                body = (json.dumps(fixture).encode() if handler.path == "/api/state"
                        else DASHBOARD.read_bytes())
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json" if handler.path == "/api/state" else "text/html; charset=utf-8")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            self.page.unroute("**/video_feed*")
            self.page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="domcontentloaded")
            self.wait_for_text("siren-detected", "SIRENE")
            self.assertTrue(stream_started.wait(2))
            self.page.wait_for_function("!document.getElementById('camera-image').hidden", timeout=4000)
            self.assertFalse(self.page.locator("#camera-image").is_hidden())
            self.assertEqual(self.page.locator("#camera-status").get_attribute("data-state"), "live")
            self.page.locator("#pause-monitor").click()
            self.assertTrue(self.page.locator("#camera-image").is_hidden())
            self.assertEqual(self.errors, [])
        finally:
            stop.set()
            self.page.goto("about:blank")
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
