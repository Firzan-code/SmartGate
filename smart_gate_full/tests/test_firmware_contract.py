"""C++ production packetizer -> Python protocol, explicit NONPHYSICAL fixtures.

Uses Zig via uv, installed Arduino hardware is never opened. The temporary host
executable and logs live in the Hermes scratch directory, not in the sketch ZIP.
"""
from pathlib import Path
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
SKETCH = ROOT / 'smart_gate_full/firmware/tes_dua_model_esp32s3'


class FirmwareContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory(
            prefix='dual_contract_', dir=os.environ.get('TMPDIR'))
        cls.executable = Path(cls._temporary.name) / 'firmware_contract_bridge.exe'

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def encode_cpp(self, samples):
        source = TESTS / 'firmware_contract_bridge.cpp'
        self.assertTrue(source.is_file(), 'Missing host bridge for the production C++ packetizer')
        if not self.executable.is_file():
            uv = shutil.which('uv')
            self.assertIsNotNone(uv, 'uv must be installed to run the C++ contract test')
            command = [uv, 'run', '--no-project', '--python', sys.executable,
                       '--with', 'ziglang==0.14.1', 'python', '-m', 'ziglang',
                       'c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                       '-I', str(SKETCH), str(source), '-o', str(self.executable)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                    text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(self.executable)], input=samples,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        return result.stdout

    def test_cpp_packetizer_output_matches_python_decoder(self):
        from smart_gate_full.backend.protocol import decode_audio_packet
        samples = (np.arange(640, dtype=np.uint16) * 3).astype('<u2')
        raw = self.encode_cpp(samples.tobytes())
        self.assertEqual(len(raw), 2 * 660)
        for sequence in range(2):
            packet = decode_audio_packet(raw[sequence * 660:(sequence + 1) * 660])
            self.assertEqual(packet.boot_id, 0x12345678)
            self.assertEqual(packet.sequence, sequence)
            self.assertEqual(packet.sample_rate, 16000)
            self.assertEqual(packet.discontinuity, sequence == 0)
            np.testing.assert_array_equal(packet.samples, samples[sequence * 320:(sequence + 1) * 320])

    def test_cpp_waveform_reaches_real_ast_and_same_http_serial_summary(self):
        """Loopback only: generated audio, C++ serializer, real local AST + Flask."""
        from ml_engine.train_siren_model import _generate_siren_sample
        from smart_gate_full.backend.app import create_app
        from smart_gate_full.backend.runtime import MonitorRuntime

        signal = _generate_siren_sample(np.random.default_rng(91), noisy=False)
        one_second = np.rint(1500 + signal / np.max(np.abs(signal)) * 900).astype('<u2')
        # Keep packets flowing while the three-second AST window is inferred.
        # The generated fixture validates transport/inference plumbing, not field accuracy.
        raw = self.encode_cpp(np.tile(one_second, 10).astype('<u2').tobytes())
        self.assertEqual(len(raw), 500 * 660)
        runtime = MonitorRuntime()
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.bind(('127.0.0.1', 0))
        client.settimeout(.05)
        replies = []
        try:
            runtime.start(camera_enabled=False, udp_host='127.0.0.1', udp_port=0)
            address = ('127.0.0.1', runtime.snapshot()['transport']['udp_port'])
            for sequence in range(500):
                client.sendto(raw[sequence * 660:(sequence + 1) * 660], address)
                time.sleep(.02)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not runtime.snapshot()['audio'].get('class_name'):
                time.sleep(.005)
            state = runtime.snapshot()
            self.assertEqual(state['audio']['status'], 'live', state['audio'])
            self.assertIn(state['audio']['class_name'],
                          {'ambulance', 'other_siren', 'traffic_noise'})
            self.assertTrue(0 <= state['audio']['siren_probability'] <= 1)
            self.assertEqual(state['transport']['packets'], 500)
            self.assertEqual(state['transport']['rejected'], 0)
            self.assertEqual(state['transport']['gaps'], 1)  # first packet declares a fresh source
            self.assertFalse(state['authorized'])
            self.assertNotIn('SUARA=MENUNGGU', state['serial_line'])
            while True:
                try:
                    reply, sender = client.recvfrom(65535)
                except socket.timeout:
                    break
                self.assertEqual(sender, address)
                self.assertLessEqual(len(reply), 512)
                self.assertTrue(reply.startswith(b'SGR1 '))
                self.assertTrue(all(32 <= value <= 126 for value in reply))
                replies.append(reply[5:].decode('ascii'))
            self.assertTrue(replies, 'No printable result returned by production UDP receiver')
            self.assertIn(state['serial_line'], replies)
            api = create_app(runtime).test_client()
            response = api.get('/api/state')
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response.headers.get('Cache-Control', ''))
            payload = response.get_json()
            self.assertEqual(payload['serial_line'], runtime.snapshot()['serial_line'])
            self.assertEqual(payload['serial_line'], state['serial_line'])
            self.assertFalse(payload['authorized'])
            time.sleep(.35)
            stale = api.get('/api/state').get_json()
            self.assertEqual(stale['audio']['status'], 'stale')
            self.assertIn('SUARA=BASI', stale['serial_line'])
            self.assertIsNone(stale['audio']['siren_detected'])
            self.assertIsNone(stale['audio']['siren_probability'])
        finally:
            client.close()
            runtime.stop()


if __name__ == '__main__':
    unittest.main()
