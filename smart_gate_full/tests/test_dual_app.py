import importlib
import unittest


class ApiTests(unittest.TestCase):
    def test_read_only_api_reports_waiting_and_no_gate_controls(self):
        try:
            module = importlib.import_module('smart_gate_full.backend.app')
        except ModuleNotFoundError:
            self.fail('Missing read-only Flask dashboard app')
        from smart_gate_full.backend.runtime import MonitorRuntime
        runtime = MonitorRuntime()
        client = module.create_app(runtime).test_client()
        response = client.get('/api/state')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])
        state = response.get_json()
        self.assertFalse(state['authorized'])
        self.assertEqual(state['audio']['status'], 'waiting')
        self.assertIn('WAJAH=', state['serial_line'])
        self.assertEqual(client.post('/api/command', json={'action': 'OPEN'}).status_code, 404)
        self.assertEqual(client.get('/health').get_json()['mode'], 'observation_only')
        stream = client.get('/video_feed', buffered=False)
        try:
            chunk = next(iter(stream.response))
            self.assertTrue(chunk.startswith(b'--frame\r\n'))
            self.assertIn(b'Content-Type: image/jpeg', chunk)
            self.assertIn(b'\xff\xd8', chunk)
        finally:
            stream.close()


if __name__ == '__main__':
    unittest.main()
