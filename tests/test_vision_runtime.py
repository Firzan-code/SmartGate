"""Runtime regressions using mocked capture; never open a camera."""
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from ml_engine import vision_ear as vision


class TestCaptureLifetime(unittest.TestCase):
    def make_detector(self):
        with patch.object(vision.EARLivenessDetector, '_init_mediapipe'):
            return vision.EARLivenessDetector()

    def test_close_keeps_model_alive_until_worker_exits(self):
        detector = self.make_detector()
        model = detector._landmarker = Mock()
        entered = threading.Event()
        resume = threading.Event()
        frame = np.zeros((32, 32, 3), np.uint8)
        capture = Mock()
        capture.read.return_value = (True, frame)

        def blocked_inference(_frame):
            entered.set()
            if not resume.wait(3):
                raise RuntimeError('Test did not unblock inference')
            return None

        with patch.object(vision.cv2, 'VideoCapture', return_value=capture), \
                patch.object(detector, '_extract_landmarks_xy', side_effect=blocked_inference):
            detector.start()
            worker = detector._thread
            real_join = worker.join
            try:
                self.assertTrue(entered.wait(1), 'Worker did not reach inference')
                with patch.object(worker, 'join', side_effect=lambda timeout: real_join(0.01)):
                    with self.assertRaisesRegex(RuntimeError, 'capture|worker|producer'):
                        detector.close()
                model.close.assert_not_called()
                self.assertIs(detector._landmarker, model)
                self.assertTrue(worker.is_alive())
            finally:
                resume.set()
                real_join(2)
                detector.close()
        self.assertFalse(worker.is_alive())
        model.close.assert_called_once_with()
        capture.release.assert_called_once_with()
        self.assertIsNone(detector._landmarker)

    def test_start_cannot_replace_a_worker_that_timed_out_stopping(self):
        detector = self.make_detector()
        entered = threading.Event()
        resume = threading.Event()
        capture = Mock()

        def blocked_read():
            entered.set()
            if not resume.wait(3):
                raise RuntimeError('Test did not unblock capture')
            return False, None

        capture.read.side_effect = blocked_read
        with patch.object(vision.cv2, 'VideoCapture', return_value=capture):
            detector.start()
            worker = detector._thread
            real_join = worker.join
            try:
                self.assertTrue(entered.wait(1))
                with patch.object(worker, 'join', side_effect=lambda timeout: real_join(0.01)):
                    with self.assertRaises(RuntimeError):
                        detector.stop()
                with patch.object(vision.threading, 'Thread') as new_worker:
                    with self.assertRaisesRegex(RuntimeError, 'capture|worker|producer'):
                        detector.start()
                new_worker.assert_not_called()
                self.assertIs(detector._thread, worker)
            finally:
                detector._running = False
                resume.set()
                real_join(2)
                detector._thread = worker
                detector.close()

    def test_start_does_not_run_while_close_is_freeing_the_model(self):
        detector = self.make_detector()
        model = detector._landmarker = Mock()
        closing = threading.Event()
        resume = threading.Event()
        starting = threading.Event()
        start_errors = []
        close_errors = []

        def blocked_close():
            closing.set()
            if not resume.wait(3):
                raise RuntimeError('Test did not unblock model close')

        def close_detector():
            try:
                detector.close()
            except Exception as exc:
                close_errors.append(exc)

        def start_detector():
            starting.set()
            try:
                detector.start()
            except Exception as exc:
                start_errors.append(exc)

        model.close.side_effect = blocked_close
        closer = threading.Thread(target=close_detector)
        starter = threading.Thread(target=start_detector)
        closer.start()
        try:
            self.assertTrue(closing.wait(1))
            with patch.object(vision.threading, 'Thread') as new_worker:
                starter.start()
                self.assertTrue(starting.wait(1))
                starter.join(0.05)
                new_worker.assert_not_called()
        finally:
            resume.set()
            closer.join(2)
            starter.join(2)
            detector._running = False
            detector._thread = None
            detector.close()
        self.assertFalse(close_errors)
        self.assertEqual(len(start_errors), 1)
        self.assertIsInstance(start_errors[0], RuntimeError)
        model.close.assert_called_once_with()

    def test_capture_is_released_when_processing_raises(self):
        detector = self.make_detector()
        detector._running = True
        capture = Mock()
        capture.read.return_value = (True, np.zeros((32, 32, 3), np.uint8))
        try:
            with patch.object(vision.cv2, 'VideoCapture', return_value=capture), \
                    patch.object(detector, 'process_frame', side_effect=ValueError('inference failed')):
                with self.assertRaisesRegex(ValueError, 'inference failed'):
                    detector._camera_loop()
            capture.release.assert_called_once_with()
            self.assertFalse(detector._running)
        finally:
            detector.close()


def synthetic_landmarks(ear):
    """Geometry fixture only, not a detected or stored face."""
    points = np.tile([80.0, 60.0], (478, 1))
    height = ear * 10
    eye = np.array([[0, 0], [6, -height], [14, -height],
                    [20, 0], [14, height], [6, height]])
    points[vision.LEFT_EYE_INDICES] = eye + [90, 50]
    points[vision.RIGHT_EYE_INDICES] = eye + [30, 50]
    return points


class TestCaptureState(unittest.TestCase):
    def make_verified_detector(self):
        with patch.object(vision.EARLivenessDetector, '_init_mediapipe'):
            detector = vision.EARLivenessDetector()
        frame = np.zeros((120, 160, 3), np.uint8)
        for timestamp, ear in ((0.0, 0.31), (0.1, 0.14), (0.2, 0.31),
                               (0.3, 0.14), (0.4, 0.31), (0.5, 0.14), (0.6, 0.14)):
            with patch.object(detector, '_extract_landmarks_xy', return_value=synthetic_landmarks(ear)):
                _, state = detector.process_frame(frame, timestamp=timestamp)
        self.assertTrue(state['liveness_verified'])
        self.assertEqual(state['total_blinks'], 2)
        self.assertGreater(state['closed_duration_ms'], 0)
        self.assertIsNotNone(detector.get_jpeg_frame())
        self.addCleanup(detector.close)
        return detector

    def assert_invalid(self, detector):
        state = detector.get_state()
        self.assertFalse(state['face_detected'])
        self.assertFalse(state['liveness_verified'])
        self.assertFalse(state['authorized'])
        self.assertEqual(state['face_identity'], 'BELUM_DIVERIFIKASI')
        self.assertIsNone(state['face_similarity'])
        self.assertIsNone(state['face_bbox'])
        for field in ('ear_left', 'ear_right', 'ear_avg', 'ear_smoothed',
                      'closed_duration_ms', 'blink_counter'):
            self.assertEqual(state[field], 0, field)
        for field in ('eye_state', 'left_eye_state', 'right_eye_state'):
            self.assertEqual(state[field], 'TIDAK_TERDETEKSI', field)
        self.assertEqual(state['trigger_reason'], 'STANDBY')
        self.assertEqual(state['total_blinks'], 2)
        self.assertFalse(detector._blink.armed)
        self.assertIsNone(detector._blink.closed_since)
        self.assertIsNone(detector._blink.verified_until)
        self.assertTrue(detector.get_jpeg_frame() is None, 'Invalid capture retained a JPEG')
        self.assertTrue(state['capture_error'])
        return state

    def test_failed_read_immediately_invalidates_cached_face_and_jpeg(self):
        with patch.object(vision.time, 'monotonic', return_value=100.0):
            detector = self.make_verified_detector()
            capture = Mock()
            capture.read.return_value = False, None
            detector._running = True

            def observe_before_retry(_delay):
                try:
                    self.assert_invalid(detector)
                    self.assertEqual(detector._blink.last_timestamp, 0.6)
                finally:
                    detector._running = False

            with patch.object(vision.cv2, 'VideoCapture', return_value=capture), \
                    patch.object(vision.time, 'sleep', side_effect=observe_before_retry):
                detector._camera_loop()
        capture.release.assert_called_once_with()

    def test_capture_exception_immediately_invalidates_cached_results(self):
        with patch.object(vision.time, 'monotonic', return_value=100.0):
            for fails_in in ('read', 'process'):
                with self.subTest(fails_in=fails_in):
                    detector = self.make_verified_detector()
                    capture = Mock()
                    capture.read.return_value = True, np.zeros((32, 32, 3), np.uint8)
                    if fails_in == 'read':
                        capture.read.side_effect = OSError('driver failed')
                    detector._running = True
                    with patch.object(vision.cv2, 'VideoCapture', return_value=capture), \
                            patch.object(detector, 'process_frame', side_effect=OSError('model failed')):
                        with self.assertRaisesRegex(OSError, 'failed'):
                            detector._camera_loop()
                    state = self.assert_invalid(detector)
                    self.assertIn('failed', state['capture_error'])
                    capture.release.assert_called_once_with()
                    self.assertFalse(detector._running)

    def test_success_after_read_failure_clears_error_without_reusing_blinks(self):
        with patch.object(vision.time, 'monotonic', return_value=100.0):
            detector = self.make_verified_detector()
            capture = Mock()
            capture.read.return_value = False, None
            detector._running = True
            with patch.object(vision.cv2, 'VideoCapture', return_value=capture), \
                    patch.object(vision.time, 'sleep', side_effect=lambda _delay: setattr(detector, '_running', False)):
                detector._camera_loop()
            self.assert_invalid(detector)
            with patch.object(detector, '_extract_landmarks_xy', return_value=synthetic_landmarks(0.31)):
                _, state = detector.process_frame(np.zeros((120, 160, 3), np.uint8), timestamp=0.7)
            self.assertIsNone(state['capture_error'])
            self.assertIsNone(detector.get_state()['capture_error'])
            self.assertTrue(state['face_detected'])
            self.assertFalse(state['liveness_verified'])
            self.assertFalse(state['authorized'])
            self.assertEqual(state['blink_counter'], 0)
            self.assertEqual(state['total_blinks'], 2)
            self.assertEqual(detector._blink.last_timestamp, 0.7)
            self.assertIsNotNone(detector.get_jpeg_frame())

    def test_expiry_during_overlay_does_not_recache_the_old_green_jpeg(self):
        clock = [100.0]
        with patch.object(vision.time, 'monotonic', side_effect=lambda: clock[0]):
            detector = self.make_verified_detector()
            real_overlay = vision.draw_vision_overlay

            def stalled_overlay(frame, landmarks, state):
                self.assertTrue(state['liveness_verified'])
                clock[0] = 100.301
                self.assert_invalid(detector)
                return real_overlay(frame, landmarks, state)

            with patch.object(detector, '_extract_landmarks_xy', return_value=synthetic_landmarks(0.14)), \
                    patch.object(vision, 'draw_vision_overlay', side_effect=stalled_overlay):
                detector.process_frame(np.zeros((120, 160, 3), np.uint8), timestamp=0.7)
            self.assertTrue(detector.get_jpeg_frame() is None, 'Expired green JPEG was republished')
            self.assert_invalid(detector)

    def test_step_cached_state_expires_without_changing_simulation_clock(self):
        clock = [100.0]
        with patch.object(vision.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(vision.EARLivenessDetector, '_init_mediapipe'):
            detector = vision.EARLivenessDetector()
            self.addCleanup(detector.close)
            for timestamp, ear in ((0.0, 0.31), (0.1, 0.14), (0.2, 0.31),
                                   (0.3, 0.14), (0.4, 0.31)):
                state = detector.step_ear_state_machine(ear, ear, timestamp=timestamp)
            self.assertTrue(state['liveness_verified'])
            clock[0] = 100.299
            self.assertTrue(detector.get_state()['liveness_verified'])
            clock[0] = 100.301
            self.assertFalse(detector.get_state()['liveness_verified'])
            self.assertEqual(detector._blink.last_timestamp, 0.4)
            state = detector.step_ear_state_machine(0.31, 0.31, timestamp=0.5)
            self.assertEqual(state['blink_counter'], 0)
            self.assertEqual(state['total_blinks'], 2)
            self.assertFalse(state['authorized'])

    def test_capture_error_is_preserved_after_the_stale_deadline(self):
        clock = [100.0]
        with patch.object(vision.time, 'monotonic', side_effect=lambda: clock[0]):
            detector = self.make_verified_detector()
            capture = Mock()
            capture.read.side_effect = OSError('specific driver failure')
            detector._running = True
            with patch.object(vision.cv2, 'VideoCapture', return_value=capture):
                with self.assertRaises(OSError):
                    detector._camera_loop()
            error = detector.get_state()['capture_error']
            self.assertIn('specific driver failure', error)
            clock[0] = 110.0
            self.assertEqual(detector.get_state()['capture_error'], error)

    def test_cached_readers_expire_results_while_capture_read_is_blocked(self):
        for first_reader in ('get_state', 'get_jpeg_frame'):
            with self.subTest(first_reader=first_reader):
                runtime_clock = [100.0]
                with patch.object(vision.time, 'monotonic', side_effect=lambda: runtime_clock[0]):
                    detector = self.make_verified_detector()
                    capture = Mock()
                    entered = threading.Event()
                    resume = threading.Event()

                    def blocked_read():
                        entered.set()
                        if not resume.wait(3):
                            raise RuntimeError('Test did not unblock capture')
                        return False, None

                    capture.read.side_effect = blocked_read
                    with patch.object(vision.cv2, 'VideoCapture', return_value=capture):
                        detector.start()
                        worker = detector._thread
                        try:
                            self.assertTrue(entered.wait(1))
                            runtime_clock[0] = 100.299
                            self.assertTrue(detector.get_state()['liveness_verified'])
                            self.assertIsNotNone(detector.get_jpeg_frame())
                            self.assertEqual(detector._blink.last_timestamp, 0.6)
                            runtime_clock[0] = 100.301
                            value = getattr(detector, first_reader)()
                            if first_reader == 'get_state':
                                self.assertFalse(value['face_detected'])
                            else:
                                self.assertIsNone(value)
                            self.assert_invalid(detector)
                            self.assertEqual(detector._blink.last_timestamp, 0.6)
                        finally:
                            detector._running = False
                            resume.set()
                            worker.join(2)
                    self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
