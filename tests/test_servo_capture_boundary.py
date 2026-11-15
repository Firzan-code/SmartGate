"""Read-to-process suspension must not disguise a pre-ARM camera read."""
import threading
from unittest import mock
import unittest


class ServoCaptureBoundaryTests(unittest.TestCase):
    def test_arm_during_read_to_process_handoff_rejects_first_frame(self):
        from smart_gate_full.backend.camera import LaptopVision
        from smart_gate_full.backend.servo_camera import ServoVision
        from smart_gate_full.backend.servo_demo import ServoController

        class Link:
            state = 0
            error = None
            def poll(self, now): pass
            def arm(self, now): return True
            def ready(self, now): return self.state == 1
            def keepalive(self, now): pass

        link = Link()
        controller = ServoController(link)
        camera = ServoVision.__new__(ServoVision)
        camera.controller = controller
        camera.camera_index = 0
        camera.capture_backend = 0
        camera._lock = threading.Lock()
        camera._running = True
        clock = [0.8]
        frame = object()
        opened = {'face_detected': True, 'left_eye_state': 'TERBUKA', 'right_eye_state': 'TERBUKA'}
        capture = mock.Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, frame)
        process = camera.process_frame

        def suspended_handoff(image, *args, **kwargs):
            # The read completed before ARM, but scheduling delays processing.
            clock[0] = 1.0
            link.state = 1
            controller.tick(1.0)
            clock[0] = 1.1
            result = process(image, *args, **kwargs)
            camera._running = False
            return result

        with mock.patch.object(LaptopVision, 'process_frame', return_value=(frame, opened)), \
                mock.patch.object(camera, 'process_frame', side_effect=suspended_handoff), \
                mock.patch('smart_gate_full.backend.camera.cv2.VideoCapture', return_value=capture), \
                mock.patch('time.monotonic', side_effect=lambda: clock[0]):
            camera._camera_loop()
        self.assertIsNone(controller.gate.started, 'Pre-ARM read was incorrectly stamped after ARM')
        capture.release.assert_called_once()

    def test_blocked_read_duration_is_not_hidden_by_processing_timestamp(self):
        from smart_gate_full.backend.camera import LaptopVision
        from smart_gate_full.backend.servo_camera import ServoVision
        from smart_gate_full.backend.servo_demo import ServoController
        controller = ServoController()
        camera = ServoVision.__new__(ServoVision)
        camera.controller = controller
        camera.camera_index = camera.capture_backend = 0
        camera._lock = threading.Lock()
        camera._running = True
        frame = object()
        opened = {'face_detected': True, 'left_eye_state': 'TERBUKA', 'right_eye_state': 'TERBUKA'}
        clock = [2.0]
        capture = mock.Mock()
        capture.isOpened.return_value = True
        def slow_read():
            clock[0] = 2.4
            camera._running = False
            return True, frame
        capture.read.side_effect = slow_read
        with mock.patch.object(LaptopVision, 'process_frame', return_value=(frame, opened)), \
                mock.patch('smart_gate_full.backend.camera.cv2.VideoCapture', return_value=capture), \
                mock.patch('time.monotonic', side_effect=lambda: clock[0]):
            camera._camera_loop()
        self.assertIsNone(controller.gate.started, 'Read older than max_gap must not count')
        capture.release.assert_called_once()


if __name__ == '__main__':
    unittest.main()
