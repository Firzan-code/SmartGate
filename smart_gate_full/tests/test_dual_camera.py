"""Camera backend tests use mocked capture, never access a physical webcam."""
import importlib
import unittest
from unittest.mock import Mock, patch
import numpy as np


class CameraBackendTests(unittest.TestCase):
    def test_selected_backend_processes_frame_and_releases_capture(self):
        try:
            module = importlib.import_module('smart_gate_full.backend.camera')
        except ModuleNotFoundError:
            self.fail('Missing selectable camera backend for live dashboard')
        from ml_engine.vision_ear import EARLivenessDetector
        with patch.object(EARLivenessDetector, '_init_mediapipe'):
            detector = module.LaptopVision(camera_index=0, backend='dshow')
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, np.zeros((32, 32, 3), np.uint8))
        detector._running = True
        def process(frame):
            detector._running = False
        with patch.object(module.cv2, 'VideoCapture', return_value=capture) as create, \
                patch.object(detector, 'process_frame', side_effect=process) as infer:
            detector._camera_loop()
        create.assert_called_once_with(0, module.cv2.CAP_DSHOW)
        self.assertEqual(infer.call_count, 1)
        capture.release.assert_called_once_with()
        detector.close()


if __name__ == '__main__':
    unittest.main()
