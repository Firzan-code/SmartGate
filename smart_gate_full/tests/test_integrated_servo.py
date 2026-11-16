import unittest
from smart_gate_full.backend.runtime import MonitorRuntime
from smart_gate_full.backend.protocol import decode_audio_packet
import struct


class IntegratedServoTests(unittest.TestCase):
    def test_decision_requires_fresh_qualified_audio_and_opt_in(self):
        runtime = MonitorRuntime(servo_enabled=True)
        runtime._stream.last_packet = 10.
        runtime._stream.servo_present = True
        runtime._audio_generation = runtime._stream.generation
        runtime._audio_at = 10.
        runtime._audio.update(status='live', siren_detected=True, clipped=False,
                              siren_probability=.95, class_probability=.9)
        self.assertEqual(runtime.snapshot(10.1)['servo']['command'], 'OPEN')
        runtime.servo_enabled = False
        self.assertEqual(runtime.snapshot(10.1)['servo']['command'], 'DISABLED')
        runtime.servo_enabled = True
        runtime._audio['clipped'] = True
        self.assertEqual(runtime.snapshot(10.1)['servo']['command'], 'HOLD')
        runtime._audio['clipped'] = False
        runtime._audio['class_probability'] = .7
        self.assertEqual(runtime.snapshot(10.1)['servo']['command'], 'HOLD')
        self.assertEqual(runtime.snapshot(11.)['servo']['command'], 'INVALID')

    def test_telemetry_keeps_audio_contract(self):
        for code, state in enumerate(['disabled', 'closed', 'open', 'cooldown', 'error']):
            raw = struct.pack('<4sIIIHH', b'SGA1', 1, 2, 16000, 320, 3 | (code << 2))
            packet = decode_audio_packet(raw + bytes(640))
            self.assertTrue(packet.discontinuity)
            self.assertTrue(packet.servo_present)
            self.assertEqual(packet.servo_state, state)
