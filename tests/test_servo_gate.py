"""Time-defined face/open-eye trigger; no model or hardware."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'smart_gate_full/backend/servo_demo.py'


class OpenEyeGateTests(unittest.TestCase):
    def test_five_continuous_seconds_fire_once(self):
        self.assertTrue(PATH.is_file(), 'Missing five-second servo gate')
        from smart_gate_full.backend.servo_demo import OpenEyeGate
        gate = OpenEyeGate()
        state = {'face_detected': True, 'left_eye_state': 'TERBUKA',
                 'right_eye_state': 'TERBUKA', 'face_bbox': [10, 10, 110, 110]}
        events = []
        for index in range(61):
            events.append(gate.update(state, index / 10, now=index / 10))
        self.assertFalse(any(events[:50]))
        self.assertTrue(events[50])
        self.assertEqual(sum(events), 1)
        self.assertTrue(gate.fired)

    def test_face_jump_does_not_join_two_faces(self):
        from smart_gate_full.backend.servo_demo import OpenEyeGate
        gate = OpenEyeGate()
        for index in range(50):
            state = {'face_detected': True, 'left_eye_state': 'TERBUKA',
                     'right_eye_state': 'TERBUKA', 'face_bbox': [0, 0, 100, 100]}
            gate.update(state, index / 10, now=index / 10)
        state['face_bbox'] = [500, 0, 600, 100]
        self.assertFalse(gate.update(state, 5.0, now=5.0))
        self.assertEqual(gate.elapsed, 0)

    def test_closure_loss_transition_and_gap_reset(self):
        from smart_gate_full.backend.servo_demo import OpenEyeGate
        for change in ({'face_detected': False}, {'left_eye_state': 'TERTUTUP'},
                       {'right_eye_state': 'TRANSISI'}, {'capture_error': 'failed'}):
            with self.subTest(change=change):
                gate = OpenEyeGate()
                state = {'face_detected': True, 'left_eye_state': 'TERBUKA', 'right_eye_state': 'TERBUKA'}
                for index in range(49):
                    gate.update(state, index / 10, now=index / 10)
                gate.update(dict(state, **change), 4.9, now=4.9)
                self.assertFalse(gate.update(state, 5.0, now=5.0))
                self.assertEqual(gate.elapsed, 0)
        gate = OpenEyeGate()
        for index in range(49):
            gate.update(state, index / 10, now=index / 10)
        self.assertFalse(gate.update(state, 5.2, now=5.2))
        self.assertEqual(gate.elapsed, 0)

    def test_cached_frames_and_stale_clock_never_fire(self):
        from smart_gate_full.backend.servo_demo import OpenEyeGate
        gate = OpenEyeGate()
        state = {'face_detected': True, 'left_eye_state': 'TERBUKA', 'right_eye_state': 'TERBUKA'}
        gate.update(state, 0., now=0.)
        for index in range(1, 80):
            self.assertFalse(gate.update(state, 0., now=index / 10))
        self.assertFalse(gate.fired)
        for timestamp in (float('nan'), float('inf'), None, -1):
            self.assertFalse(gate.update(state, timestamp, now=8.))
        for option in (float('nan'), float('inf'), 0., -1.):
            with self.assertRaises(ValueError):
                OpenEyeGate(seconds=option)


if __name__ == '__main__':
    unittest.main()
