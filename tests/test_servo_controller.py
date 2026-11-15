"""Integrated vision-event/controller contracts, with simulated time and no camera."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OPEN = {'face_detected': True, 'left_eye_state': 'TERBUKA', 'right_eye_state': 'TERBUKA'}


class ControllerTests(unittest.TestCase):
    def test_simulation_counts_from_frames_not_http_polls(self):
        from smart_gate_full.backend.servo_demo import OpenEyeGate
        self.assertTrue(hasattr(__import__('smart_gate_full.backend.servo_demo', fromlist=['ServoController']),
                                'ServoController'), 'Missing frame-to-controller integration')
        from smart_gate_full.backend.servo_demo import ServoController
        controller = ServoController()
        for i in range(51):
            controller.on_frame(OPEN, i / 10, now=i / 10)
            controller.tick(i / 10)
        self.assertTrue(controller.snapshot()['gate']['fired'])
        self.assertFalse(controller.snapshot()['authorized'])
        self.assertEqual(controller.snapshot()['mode'], 'SIMULASI TANPA GERAK')

    def test_hardware_waits_for_arm_then_opens_only_once(self):
        from smart_gate_full.backend.servo_demo import ServoController
        class Link:
            state = 0
            error = None
            opens = 0
            def poll(self, now): pass
            def arm(self, now): return True
            def ready(self, now): return self.state == 1
            def fresh(self, now): return True
            def keepalive(self, now): pass
            def open_once(self, now):
                self.opens += 1
                self.state = 2
                return True
            def snapshot(self): return {'state': self.state}
        link = Link()
        controller = ServoController(link)
        for i in range(51):
            controller.on_frame(OPEN, i / 10, now=i / 10)
        self.assertFalse(controller.gate.fired)
        self.assertEqual(link.opens, 0)
        link.state = 1
        for i in range(51, 112):
            controller.on_frame(OPEN, i / 10, now=i / 10)
            controller.tick(i / 10)
        self.assertEqual(link.opens, 1)
        self.assertTrue(controller.gate.fired)

    def test_frame_captured_before_arm_cannot_start_countdown(self):
        from smart_gate_full.backend.servo_demo import ServoController
        class Link:
            state = 1
            error = None
            def poll(self, now): pass
            def arm(self, now): return True
            def ready(self, now): return True
            def fresh(self, now): return True
            def keepalive(self, now): pass
            def snapshot(self): return {'state': self.state}
        controller = ServoController(Link())
        controller.tick(1.)
        controller.on_frame(OPEN, .9, now=1.1)
        self.assertIsNone(controller.gate.started)
        controller.on_frame(OPEN, 1.2, now=1.2)
        self.assertEqual(controller.gate.started, 1.2)


if __name__ == '__main__':
    unittest.main()
