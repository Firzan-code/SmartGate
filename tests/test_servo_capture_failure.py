"""Capture failure must break eye-open continuity even below the gap limit."""
from unittest import mock
import unittest


class ServoCaptureFailureTests(unittest.TestCase):
    def test_read_failure_resets_controller_immediately(self):
        from smart_gate_full.backend.servo_camera import ServoVision
        from smart_gate_full.backend.camera import LaptopVision
        from smart_gate_full.backend.servo_demo import ServoController
        controller = ServoController()
        state = {'face_detected': True, 'left_eye_state': 'TERBUKA', 'right_eye_state': 'TERBUKA'}
        for index in range(49):
            controller.on_frame(state, index / 10, now=index / 10)
        camera = ServoVision.__new__(ServoVision)
        camera.controller = controller
        with mock.patch.object(LaptopVision, '_invalidate_capture_locked'):
            with mock.patch('smart_gate_full.backend.servo_camera.time.monotonic', return_value=4.85):
                camera._invalidate_capture_locked('read failed')
        self.assertEqual(controller.gate.elapsed, 0)
        controller.on_frame(state, 4.9, now=4.9)
        self.assertEqual(controller.gate.started, 4.9)
        self.assertFalse(controller.gate.fired)


if __name__ == '__main__':
    unittest.main()
