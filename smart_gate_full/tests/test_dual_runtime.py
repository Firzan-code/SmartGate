"""No hardware is opened here; ports used below are loopback test endpoints."""
import importlib
import socket
import struct
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch


def packet(seq, flags=0, boot=1):
    return struct.pack('<4sIIIHH', b'SGA1', boot, seq, 16000, 320, flags) + struct.pack('<320H', *([1400] * 320))


class RuntimeTests(unittest.TestCase):
    def test_no_input_is_waiting_not_non_siren(self):
        try:
            module = importlib.import_module('smart_gate_full.backend.runtime')
        except ModuleNotFoundError:
            self.fail('Missing shared live runtime for dashboard and ESP')
        runtime = module.MonitorRuntime()
        state = runtime.snapshot()
        self.assertEqual(state['audio']['status'], 'waiting')
        self.assertIsNone(state['audio']['siren_detected'])
        self.assertIsNone(state['audio']['siren_probability'])
        self.assertEqual(state['vision']['status'], 'waiting')
        self.assertFalse(state['authorized'])
        self.assertIn('MENUNGGU', state['serial_line'])
        self.assertLessEqual(len(state['serial_line'].encode('ascii')) + 5, 512)

    def test_loopback_udp_printable_reply_and_stale_invalidation(self):
        from smart_gate_full.backend.runtime import MonitorRuntime
        runtime = MonitorRuntime()
        self.assertTrue(hasattr(runtime, 'start'), 'Missing UDP receive/inference/result worker lifecycle')
        class TestClassifier:
            def predict(self, window):
                return {'status': 'live', 'source': 'MAX9814_ESP32', 'siren_detected': True,
                        'siren_probability': .91, 'consecutive_hits': 2, 'error': None}
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.bind(('127.0.0.1', 0))
        client.settimeout(2.)
        try:
            runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0,
                          classifier=TestClassifier())
            address = ('127.0.0.1', runtime.snapshot()['transport']['udp_port'])
            for seq in range(50):
                client.sendto(packet(seq), address)
                time.sleep(.002)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if runtime.snapshot()['audio']['status'] == 'live':
                    break
                time.sleep(.01)
            self.assertEqual(runtime.snapshot()['audio']['status'], 'live')
            raw, sender = client.recvfrom(512)
            self.assertTrue(raw.startswith(b'SGR1 '))
            self.assertEqual(sender, address)
            self.assertTrue(all(32 <= c <= 126 for c in raw))
            # Pause long enough to invalidate input; never keep the old positive.
            time.sleep(.4)
            state = runtime.snapshot()
            self.assertEqual(state['audio']['status'], 'stale')
            self.assertIsNone(state['audio']['siren_detected'])
            client.sendto(packet(52), address)
            time.sleep(.04)
            state = runtime.snapshot()
            self.assertEqual(state['audio']['status'], 'buffering')
            self.assertGreaterEqual(state['transport']['gaps'], 1)
            self.assertNotIn('SUARA=SIRENE', state['serial_line'])
        finally:
            client.close()
            if hasattr(runtime, 'stop'):
                runtime.stop()

    def test_oversized_loopback_datagram_is_rejected_without_killing_receiver(self):
        from smart_gate_full.backend.runtime import MonitorRuntime
        runtime = MonitorRuntime()
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.bind(('127.0.0.1', 0))
        try:
            runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0,
                          classifier=object())
            address = ('127.0.0.1', runtime.snapshot()['transport']['udp_port'])
            valid = packet(0)
            # Keep a valid prefix: the complete length must be validated, not truncated.
            client.sendto(valid + bytes(4096 - len(valid)), address)
            client.sendto(valid, address)
            deadline = time.monotonic() + 2
            state = runtime.snapshot()
            while time.monotonic() < deadline and not state['transport']['packets']:
                if state['audio']['status'] == 'error':
                    break
                time.sleep(.005)
                state = runtime.snapshot()
            self.assertEqual(state['transport']['packets'], 1, state['audio'])
            self.assertEqual(state['transport']['rejected'], 1)
            self.assertEqual(state['audio']['status'], 'buffering')
            self.assertTrue(next(t for t in runtime._threads if t.name == 'audio-network').is_alive())
        finally:
            client.close()
            runtime.stop()

    def test_fatal_receive_error_survives_in_flight_inference(self):
        from dataclasses import replace
        from smart_gate_full.backend.runtime import MonitorRuntime
        runtime = MonitorRuntime()
        inference_entered = threading.Event()
        release_inference = threading.Event()
        fail_receive = threading.Event()
        inference_published = threading.Event()
        windows = []
        positive = {'status': 'live', 'source': 'MAX9814_ESP32', 'siren_detected': True,
                    'siren_probability': .99, 'consecutive_hits': 2, 'error': None,
                    'spectrum_freqs_hz': [1000.], 'spectrum_magnitudes': [1.]}

        class BlockingClassifier:
            def predict(self, window):
                windows.append(window)
                inference_entered.set()
                if not release_inference.wait(5):
                    raise RuntimeError('Test did not release inference')
                return positive

        packets = iter(packet(seq) for seq in range(50))
        def receive(size):
            try:
                return next(packets), ('127.0.0.1', 12345)
            except StopIteration:
                fail_receive.wait(5)
                raise OSError('injected fatal receive failure')

        sock = Mock()
        sock.getsockname.return_value = ('127.0.0.1', 5006)
        sock.recvfrom.side_effect = receive
        publish = runtime._publish_audio
        def observe_publication(window, result):
            try:
                return publish(window, result)
            finally:
                inference_published.set()

        with patch('smart_gate_full.backend.runtime.socket.socket', return_value=sock), \
                patch.object(runtime, '_publish_audio', side_effect=observe_publication):
            try:
                runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0,
                              classifier=BlockingClassifier())
                self.assertTrue(inference_entered.wait(2), 'No in-flight inference after 50 packets')
                self.assertEqual(runtime.snapshot()['transport']['packets'], 50)
                fail_receive.set()
                receiver = next(t for t in runtime._threads if t.name == 'audio-network')
                receiver.join(2)
                self.assertFalse(receiver.is_alive(), 'Injected fatal receive error did not stop receiver')
                failed = runtime.snapshot()
                self.assertEqual(failed['audio']['status'], 'error')
                self.assertIn('injected fatal receive failure', failed['audio']['error'])
                release_inference.set()
                self.assertTrue(inference_published.wait(2), 'In-flight inference never completed')
                state = runtime.snapshot()
                self.assertEqual(state['audio']['status'], 'error', state['audio'])
                self.assertEqual(state['audio']['error'], failed['audio']['error'])
                self.assertIsNone(state['audio']['siren_detected'])
                self.assertIsNone(state['audio']['siren_probability'])
                self.assertEqual(state['audio']['consecutive_hits'], 0)
                self.assertEqual(state['audio']['spectrum_magnitudes'], [])
                self.assertEqual(state['transport']['buffer_samples'], 0)
                self.assertGreater(state['transport']['generation'], windows[0].generation)
                self.assertIn('SUARA=ERROR', state['serial_line'])
                # Even a current-generation result must not silently resume a dead receiver.
                fresh = replace(windows[0], generation=state['transport']['generation'],
                                received_at=time.monotonic())
                self.assertFalse(publish(fresh, positive))
                runtime._audio_error('late classifier failure')
                self.assertEqual(runtime.snapshot()['audio']['error'], failed['audio']['error'])
            finally:
                fail_receive.set()
                release_inference.set()
                runtime.stop()

    def test_udp_reset_from_refused_reply_keeps_receiver_alive(self):
        from smart_gate_full.backend.runtime import MonitorRuntime
        runtime = MonitorRuntime()
        reset = ConnectionResetError(10054, 'reply port closed')
        script = [reset, reset, (packet(0), ('127.0.0.1', 12345)), reset]

        def receive(size):
            if script:
                item = script.pop(0)
                if isinstance(item, BaseException):
                    raise item
                return item
            time.sleep(.01)
            raise socket.timeout()

        def refused(state):
            return [e for e in state['events'] if 'ditolak' in e['message']]

        sock = Mock()
        sock.getsockname.return_value = ('127.0.0.1', 5006)
        sock.recvfrom.side_effect = receive
        with patch('smart_gate_full.backend.runtime.socket.socket', return_value=sock):
            try:
                runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0, classifier=object())
                deadline = time.monotonic() + 2
                state = runtime.snapshot()
                while time.monotonic() < deadline and (script or len(refused(state)) < 2):
                    time.sleep(.01)
                    state = runtime.snapshot()
                receiver = next(t for t in runtime._threads if t.name == 'audio-network')
                self.assertTrue(receiver.is_alive(), state['audio'])
                self.assertNotEqual(state['audio']['status'], 'error', state['audio'])
                self.assertIsNone(state['audio']['error'])
                self.assertEqual(state['transport']['packets'], 1)
                # One notice per episode: the accepted packet re-arms it.
                self.assertEqual(len(refused(state)), 2, state['events'])
            finally:
                runtime.stop()

    @unittest.skipUnless(sys.platform == 'win32', 'Reset UDP (WSAECONNRESET) hanya terjadi di Windows')
    def test_closed_reply_port_on_windows_does_not_stop_audio(self):
        from smart_gate_full.backend.runtime import MonitorRuntime
        runtime = MonitorRuntime()
        first = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        second = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for client in (first, second):
            client.bind(('127.0.0.1', 0))
            client.settimeout(2.)
        try:
            runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0, classifier=object())
            address = ('127.0.0.1', runtime.snapshot()['transport']['udp_port'])
            first.sendto(packet(0), address)
            self.assertTrue(first.recvfrom(512)[0].startswith(b'SGR1 '))
            first.close()  # The next SGR1 reply now hits a closed port.
            deadline = time.monotonic() + 2
            state = runtime.snapshot()
            while time.monotonic() < deadline and (
                    not any('ditolak' in e['message'] for e in state['events'])
                    or state['transport']['seconds_since_packet'] <= .35):
                time.sleep(.01)
                state = runtime.snapshot()
            self.assertIsNone(state['audio']['error'], state['audio'])
            self.assertTrue(any('ditolak' in e['message'] for e in state['events']), state['events'])
            second.sendto(packet(0, boot=2), address)
            raw, sender = second.recvfrom(512)
            self.assertTrue(raw.startswith(b'SGR1 '))
            self.assertEqual(sender, address)
            state = runtime.snapshot()
            self.assertEqual(state['transport']['packets'], 2)
            self.assertIsNone(state['audio']['error'], state['audio'])
            self.assertTrue(next(t for t in runtime._threads if t.name == 'audio-network').is_alive())
        finally:
            first.close()
            second.close()
            runtime.stop()

    def test_stale_window_cannot_publish_as_fresh(self):
        from smart_gate_full.backend.runtime import MonitorRuntime
        runtime = MonitorRuntime()
        self.assertTrue(hasattr(runtime, '_publish_audio'), 'Missing freshness check at publication boundary')
        from smart_gate_full.backend.stream import AudioWindow
        import numpy as np
        runtime._stream.generation = 3
        window = AudioWindow(np.ones(16000), 3, 49, 10., 1, 1, 1.)
        result = {'status': 'live', 'source': 'MAX9814_ESP32',
                  'siren_detected': True, 'siren_probability': .99}
        self.assertFalse(runtime._publish_audio(window, result, now=12.))
        self.assertIsNone(runtime.snapshot()['audio']['siren_detected'])
        self.assertTrue(runtime._publish_audio(window, result, now=10.1))
        runtime._stream.generation = 4
        self.assertFalse(runtime._publish_audio(window, result, now=10.2))

    def test_valid_no_face_frame_is_live_not_waiting(self):
        from smart_gate_full.backend.runtime import MonitorRuntime
        class ObservedNoFace:
            def get_state(self):
                return {'updated_at': '-', 'capture_error': None, 'eye_state': 'TIDAK_TERDETEKSI',
                        'face_detected': False, 'ear_left': 0., 'ear_right': 0.}
        runtime = MonitorRuntime()
        runtime._detector = ObservedNoFace()
        state = runtime.snapshot()
        self.assertEqual(state['vision']['status'], 'live')
        self.assertFalse(state['vision']['face_detected'])
        self.assertIn('WAJAH=TIDAK_TERDETEKSI', state['serial_line'])

    def test_camera_disabled_is_explicit_not_silent_waiting(self):
        from smart_gate_full.backend.runtime import MonitorRuntime
        runtime = MonitorRuntime()
        try:
            runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0, classifier=object())
            state = runtime.snapshot()
            self.assertEqual(state['vision']['status'], 'error')
            self.assertIn('dinonaktifkan', state['vision']['error'])
        finally:
            runtime.stop()

    def test_real_ast_over_loopback_udp_fixture_not_physical_audio(self):
        from smart_gate_full.backend.runtime import MonitorRuntime
        from ml_engine.train_siren_model import _generate_siren_sample
        import numpy as np
        signal = _generate_siren_sample(np.random.default_rng(91), noisy=False)
        adc = np.rint(1500 + signal / np.max(np.abs(signal)) * 900).astype('<u2')
        runtime = MonitorRuntime()
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.bind(('127.0.0.1', 0))
        try:
            runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0)
            address = ('127.0.0.1', runtime.snapshot()['transport']['udp_port'])
            for seq in range(500):
                block = adc[(seq % 50)*320:(seq % 50+1)*320]
                raw = struct.pack('<4sIIIHH', b'SGA1', 91, seq, 16000, 320, 0) + block.tobytes()
                client.sendto(raw, address)
                time.sleep(.02)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not runtime.snapshot()['audio'].get('class_name'):
                time.sleep(.005)
            state = runtime.snapshot()
            self.assertEqual(state['audio']['status'], 'live', state)
            self.assertIn(state['audio']['class_name'], {'ambulance', 'other_siren', 'traffic_noise'})
            self.assertTrue(0 <= state['audio']['siren_probability'] <= 1)
            self.assertEqual(state['transport']['packets'], 500)
            self.assertEqual(state['transport']['gaps'], 0)
            self.assertNotIn('SUARA=MENUNGGU', state['serial_line'])
        finally:
            client.close()
            runtime.stop()

    def test_runtime_reuse_is_explicitly_disallowed(self):
        from smart_gate_full.backend.runtime import MonitorRuntime
        runtime = MonitorRuntime()
        runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0, classifier=object())
        runtime.stop()
        try:
            with self.assertRaisesRegex(RuntimeError, 'baru|ulang|reuse'):
                runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0, classifier=object())
        finally:
            runtime.stop()


if __name__ == '__main__':
    unittest.main()
