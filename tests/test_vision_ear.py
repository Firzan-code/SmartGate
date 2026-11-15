"""Tes vision tidak membuka kamera dan tidak memakai wajah pribadi."""
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from ml_engine import vision_ear as vision


def landmark_fixture():
    """Koordinat buatan khusus tes geometri; bukan hasil inference model."""
    angles = np.linspace(0, 2 * np.pi, 478, endpoint=False)
    points = np.column_stack((200 + 130 * np.cos(angles), 230 + 160 * np.sin(angles)))
    eye = np.array([[0, 0], [12, -6], [28, -6], [40, 0], [28, 6], [12, 6]], dtype=float)
    points[vision.LEFT_EYE_INDICES] = eye + [235, 205]
    points[vision.RIGHT_EYE_INDICES] = eye + [125, 205]
    return points


class TestOverlay(unittest.TestCase):
    def test_overlay_renders_face_box_measurements_and_side_panel(self):
        frame = np.full((480, 400, 3), 40, dtype=np.uint8)
        original = frame.copy()
        landmarks = landmark_fixture()
        state = {
            'face_detected': True,
            'liveness_verified': False,
            'ear_left': 0.30, 'ear_right': 0.30, 'ear_avg': 0.30,
            'eye_state': 'TERBUKA', 'blink_counter': 0, 'total_blinks': 0,
        }
        self.assertTrue(
            hasattr(vision, 'draw_vision_overlay'),
            'Belum ada overlay kotak wajah, garis EAR, dan panel samping',
        )
        rendered = vision.draw_vision_overlay(frame, landmarks, state)
        np.testing.assert_array_equal(frame, original)
        self.assertGreater(rendered.shape[1], frame.shape[1])
        self.assertEqual(rendered.shape[0], frame.shape[0])
        x1, y1, x2, y2 = vision.face_bounding_box(landmarks, frame.shape)
        np.testing.assert_array_equal(rendered[y2, x1], vision.COLOR_WAITING)
        # Titik tengah p1-p4 (horizontal), dan p2-p6 / p3-p5 (bukaan).
        np.testing.assert_array_equal(rendered[205, 255], vision.COLOR_EYE_WIDTH)
        np.testing.assert_array_equal(rendered[202, 247], vision.COLOR_EYE_OPENING)
        np.testing.assert_array_equal(rendered[202, 263], vision.COLOR_EYE_OPENING)
        ok, jpeg = cv2.imencode('.jpg', rendered)
        self.assertTrue(ok)
        self.assertGreater(jpeg.size, 1000)


class TestFrameIntegration(unittest.TestCase):
    def test_missing_model_raises_with_actual_cause(self):
        with patch.object(vision, 'FACE_LANDMARKER_MODEL_PATH', vision.BASE_DIR / 'models' / 'missing.task'):
            with self.assertRaisesRegex(RuntimeError, 'missing.task'):
                vision.EARLivenessDetector()

    def test_missing_mediapipe_raises_instead_of_silent_no_face(self):
        with patch.object(vision, 'HAS_MEDIAPIPE', False):
            with self.assertRaises(RuntimeError):
                vision.EARLivenessDetector()

    def test_identity_enrollment_is_disabled_in_eye_only_module(self):
        with patch.object(vision.EARLivenessDetector, '_init_mediapipe'):
            detector = vision.EARLivenessDetector()
        self.assertFalse(detector.get_state()['authorized'])
        with self.assertRaises(NotImplementedError):
            detector.register_face('test', np.zeros((480, 640, 3), np.uint8))

    def test_large_face_jump_resets_pending_blinks(self):
        with patch.object(vision.EARLivenessDetector, '_init_mediapipe'):
            detector = vision.EARLivenessDetector()
        frame = np.zeros((480, 1000, 3), np.uint8)
        first = landmark_fixture()
        moved = first + [550, 0]
        with patch.object(detector, '_extract_landmarks_xy', return_value=first):
            detector.process_frame(frame, timestamp=0.0)
        detector.step_ear_state_machine(0.14, 0.14, timestamp=0.1)
        detector.step_ear_state_machine(0.31, 0.31, timestamp=0.3)
        with patch.object(detector, '_extract_landmarks_xy', return_value=moved):
            _, state = detector.process_frame(frame, timestamp=0.4)
        self.assertEqual(state['blink_counter'], 0)
        self.assertFalse(state['liveness_verified'])

    def test_face_disappearance_clears_duration_and_verified_state(self):
        with patch.object(vision.EARLivenessDetector, '_init_mediapipe'):
            detector = vision.EARLivenessDetector()
        detector.step_ear_state_machine(0.31, 0.31, timestamp=0.0)
        detector.step_ear_state_machine(0.14, 0.14, timestamp=0.1)
        detector.step_ear_state_machine(0.14, 0.14, timestamp=0.2)
        with patch.object(detector, '_extract_landmarks_xy', return_value=None):
            _, state = detector.process_frame(np.zeros((480, 640, 3), np.uint8), timestamp=0.3)
        self.assertEqual(state['closed_duration_ms'], 0.0)
        self.assertEqual(state['ear_smoothed'], 0.0)
        self.assertFalse(state['face_detected'])
        self.assertFalse(state['liveness_verified'])

    def test_detector_uses_timestamp_duration_instead_of_frame_limit(self):
        with patch.object(vision.EARLivenessDetector, '_init_mediapipe'):
            detector = vision.EARLivenessDetector()
        for i in range(97):
            now = i / 60
            ear = 0.14 if (0.3 <= now < 0.5 or 0.9 <= now < 1.1) else 0.31
            state = detector.step_ear_state_machine(ear, ear, timestamp=now)
        self.assertEqual(state['blink_counter'], 2)
        self.assertTrue(state['liveness_verified'])
        self.assertFalse(state['authorized'])
        self.assertEqual(state['face_identity'], 'BELUM_DIVERIFIKASI')

    def test_process_frame_exposes_overlay_without_authorizing_identity(self):
        # Ganti hanya inference landmark; geometri, EAR, state, overlay dan JPEG nyata.
        with patch.object(vision.EARLivenessDetector, '_init_mediapipe'):
            detector = vision.EARLivenessDetector()
        frame = np.full((480, 400, 3), 40, dtype=np.uint8)
        with patch.object(detector, '_extract_landmarks_xy', return_value=landmark_fixture()):
            rendered, state = detector.process_frame(frame)
        self.assertEqual(rendered.shape[1], 400 + vision.PANEL_WIDTH)
        self.assertEqual(len(state['face_bbox']), 4)
        self.assertFalse(state['authorized'])
        self.assertEqual(state['face_identity'], 'BELUM_DIVERIFIKASI')
        self.assertEqual(state['eye_state'], 'TERBUKA')
        decoded = cv2.imdecode(np.frombuffer(detector.get_jpeg_frame(), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, rendered.shape)


class TestTimedBlink(unittest.TestCase):
    def test_rejects_wink_short_noise_and_long_closure(self):
        for duration, left, right in ((0.02, 0.14, 0.14), (0.7, 0.14, 0.14), (0.2, 0.10, 0.31)):
            with self.subTest(duration=duration, left=left, right=right):
                tracker = vision.BlinkStateMachine()
                tracker.update(0.31, 0.31, 0.0)
                tracker.update(left, right, 0.1)
                for t in np.arange(0.11, 0.1 + duration, 0.01):
                    tracker.update(left, right, float(t))
                state = tracker.update(0.31, 0.31, 0.1 + duration)
                self.assertEqual(state['blink_counter'], 0)

    def test_old_blink_expires_outside_five_second_window(self):
        tracker = vision.BlinkStateMachine()
        for i in range(190):
            now = i / 30
            ear = 0.14 if (0.2 <= now < 0.4 or 5.8 <= now < 6.0) else 0.31
            state = tracker.update(ear, ear, now)
        self.assertEqual(state['total_blinks'], 2)
        self.assertEqual(state['blink_counter'], 1)
        self.assertFalse(state['liveness_verified'])

    def test_invalid_configuration_is_rejected(self):
        for kwargs in ({'ear_threshold': 0.3, 'open_threshold': 0.2},
                       {'required_blinks': 0}, {'blink_window_sec': 0},
                       {'min_closed_sec': -0.1}, {'max_closed_sec': 0.01},
                       {'max_tracking_gap_sec': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                vision.BlinkStateMachine(**kwargs)

    def test_rejects_invalid_values_and_non_monotonic_timestamps(self):
        for bad in (float('nan'), float('inf'), -0.1):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                vision.BlinkStateMachine().update(bad, 0.31, 0.0)
        for bad_time in (float('nan'), float('inf')):
            with self.subTest(timestamp=bad_time), self.assertRaises(ValueError):
                vision.BlinkStateMachine().update(0.31, 0.31, bad_time)
        tracker = vision.BlinkStateMachine()
        tracker.update(0.31, 0.31, 1.0)
        with self.assertRaises(ValueError):
            tracker.update(0.31, 0.31, 0.9)

    def test_verification_expires_without_extending_from_old_blinks(self):
        tracker = vision.BlinkStateMachine()
        for i in range(151):
            now = i / 30
            ear = 0.14 if (0.3 <= now < 0.5 or 0.9 <= now < 1.1) else 0.31
            state = tracker.update(ear, ear, now)
        self.assertEqual(state['total_blinks'], 2)
        self.assertFalse(state['liveness_verified'], 'Kedipan lama tidak boleh memperpanjang hasil terus-menerus')
        self.assertEqual(state['blink_counter'], 0)

    def test_tracking_gap_discards_previous_blink(self):
        tracker = vision.BlinkStateMachine()
        for t, ear in [(0.0, 0.31), (0.1, 0.14), (0.3, 0.31),
                       (1.0, 0.31), (1.1, 0.14), (1.3, 0.31)]:
            state = tracker.update(ear, ear, t)
        self.assertEqual(state['blink_counter'], 1)
        self.assertFalse(state['liveness_verified'])

    def test_face_loss_clears_pending_blinks(self):
        tracker = vision.BlinkStateMachine()
        tracker.update(0.31, 0.31, 0.0)
        tracker.update(0.14, 0.14, 0.1)
        self.assertEqual(tracker.update(0.31, 0.31, 0.3)['blink_counter'], 1)
        state = tracker.update(0.0, 0.0, 0.4, face_detected=False)
        self.assertEqual(state['blink_counter'], 0)
        self.assertFalse(state['liveness_verified'])
        self.assertFalse(state['face_detected'])
        self.assertFalse(tracker.armed)

    def test_requires_open_eyes_before_starting_a_blink(self):
        tracker = vision.BlinkStateMachine()
        tracker.update(0.14, 0.14, 1.0)
        state = tracker.update(0.31, 0.31, 1.2)
        self.assertEqual(state['blink_counter'], 0, 'Mata tertutup saat pertama terlihat bukan kedipan')

    def test_same_two_blinks_at_different_fps(self):
        self.assertTrue(hasattr(vision, 'BlinkStateMachine'), 'Belum ada penghitung kedipan berbasis waktu')
        for fps in (15, 30, 60):
            with self.subTest(fps=fps):
                tracker = vision.BlinkStateMachine()
                for i in range(int(1.6 * fps) + 1):
                    now = i / fps
                    ear = 0.14 if (0.3 <= now < 0.5 or 0.9 <= now < 1.1) else 0.31
                    state = tracker.update(ear, ear, now)
                self.assertEqual(state['blink_counter'], 2)
                self.assertTrue(state['liveness_verified'])
                self.assertFalse(state['authorized'])


class TestRealModel(unittest.TestCase):
    def test_video_inference_uses_real_model_and_releases_it(self):
        detector = vision.EARLivenessDetector()
        self.assertTrue(hasattr(detector, 'close'), 'Model belum memiliki resource cleanup')
        try:
            with patch.object(detector._landmarker, 'detect_for_video', wraps=detector._landmarker.detect_for_video) as detect:
                _, state = detector.process_frame(np.zeros((480, 640, 3), np.uint8), timestamp=1.0)
            self.assertTrue(detect.called)
            self.assertFalse(state['face_detected'])
            self.assertFalse(state['authorized'])
        finally:
            detector.close()
        self.assertIsNone(detector._landmarker)


if __name__ == '__main__':
    unittest.main()
