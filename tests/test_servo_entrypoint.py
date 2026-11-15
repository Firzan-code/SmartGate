"""Device-free checks for new launcher, vision hook and HTTP state."""
from pathlib import Path
import importlib.util
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ServoEntryTests(unittest.TestCase):
    def test_readonly_http_and_frame_hook(self):
        path = ROOT / 'smart_gate_full/backend/servo_camera.py'
        self.assertTrue(path.is_file(), 'Missing new-frame vision callback')
        from smart_gate_full.backend.servo_camera import ServoVision
        from smart_gate_full.backend.servo_demo import ServoController
        from smart_gate_full.backend.camera import LaptopVision
        controller = ServoController()
        detector = ServoVision.__new__(ServoVision)
        detector.controller = controller
        frame = object()
        state = {'face_detected': True, 'left_eye_state': 'TERBUKA', 'right_eye_state': 'TERBUKA'}
        with mock.patch.object(LaptopVision, 'process_frame', return_value=(frame, state)):
            for i in range(51):
                with mock.patch('smart_gate_full.backend.servo_camera.time.monotonic', return_value=i / 10):
                    detector.process_frame(frame, captured_at=i / 10)
        self.assertTrue(controller.gate.fired)
        from run_servo_demo import create_app
        detector.get_state = lambda: state
        detector.get_jpeg_frame = lambda: None
        client = create_app(controller, detector).test_client()
        response = client.get('/api/state')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['authorized'])
        self.assertTrue(response.json['servo']['gate']['fired'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(client.post('/api/command', json={'open': True}).status_code, 404)
        with client.get('/') as page:
            self.assertIn('5 detik', page.get_data(as_text=True))

    def test_cli_rejects_missing_ip_and_invalid_duration_before_startup(self):
        self.assertTrue((ROOT / 'run_servo_demo.py').is_file(), 'Missing servo launcher')
        from run_servo_demo import main
        for args in (['--enable-servo'], ['--seconds', 'nan'], ['--seconds', '-1'],
                     ['--enable-servo', '--esp-ip', 'not-an-ip']):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                main(args)

    def test_default_launcher_never_constructs_hardware_link(self):
        from run_servo_demo import main
        with mock.patch('smart_gate_full.backend.servo_camera.ServoVision') as vision, \
                mock.patch('smart_gate_full.backend.servo_link.ServoLink') as link, \
                mock.patch('werkzeug.serving.make_server') as server:
            self.assertEqual(main(['--seconds', '.001']), 0)
            link.assert_not_called()
            vision.return_value.start.assert_called_once()
            vision.return_value.close.assert_called_once()
            server.return_value.server_close.assert_called_once()

    def test_worker_failure_still_disarms_and_closes(self):
        from run_servo_demo import main
        with mock.patch('smart_gate_full.backend.servo_camera.ServoVision') as vision, \
                mock.patch('smart_gate_full.backend.servo_link.ServoLink') as link, \
                mock.patch('werkzeug.serving.make_server') as server:
            vision.return_value.start.side_effect = RuntimeError('injected startup failure')
            self.assertEqual(main(['--enable-servo', '--esp-ip', '192.0.2.20']), 1)
            link.return_value.disarm.assert_called_once()
            link.return_value.close.assert_called_once()
            vision.return_value.close.assert_called_once()
            server.return_value.server_close.assert_called_once()


    def test_close_failure_still_cleans_camera_and_server(self):
        from run_servo_demo import main
        with mock.patch('smart_gate_full.backend.servo_camera.ServoVision') as vision, \
                mock.patch('smart_gate_full.backend.servo_link.ServoLink') as link, \
                mock.patch('werkzeug.serving.make_server') as server:
            link.return_value.close.side_effect = OSError('injected close failure')
            self.assertEqual(main(['--enable-servo', '--esp-ip', '192.0.2.20', '--seconds', '.001']), 1)
            vision.return_value.close.assert_called_once()
            server.return_value.server_close.assert_called_once()

    def test_unsent_disarm_warns_watchdog_fallback(self):
        from run_servo_demo import main
        with mock.patch('smart_gate_full.backend.servo_camera.ServoVision'), \
                mock.patch('smart_gate_full.backend.servo_link.ServoLink') as link, \
                mock.patch('werkzeug.serving.make_server'), mock.patch('sys.stderr') as stderr:
            link.return_value.disarm.return_value = False
            self.assertEqual(main(['--enable-servo', '--esp-ip', '192.0.2.20', '--seconds', '.001']), 1)
            self.assertIn('watchdog', str(stderr.write.call_args_list))


if __name__ == '__main__':
    unittest.main()
