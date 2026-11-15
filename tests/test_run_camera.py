"""CLI smoke test memakai frame kosong dan model nyata; bukan kamera pribadi."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import weakref
from unittest.mock import Mock, patch

import cv2
import numpy as np

import run_camera

BASE = Path(__file__).resolve().parents[1]


class TestCameraRunner(unittest.TestCase):
    @contextmanager
    def _mocked_static_image(self, keys, visibility):
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        detector = Mock()
        detector.get_state.return_value = {'backend': 'mocked'}
        detector.process_frame.return_value = (
            frame, {'face_detected': False, 'total_blinks': 0, 'processing_ms': 2.0})
        gui = {
            'VideoCapture': Mock(side_effect=AssertionError('Static image must not open capture')),
            'imread': Mock(return_value=frame),
            'imwrite': Mock(side_effect=AssertionError('Snapshot was not requested')),
            'namedWindow': Mock(), 'resizeWindow': Mock(), 'imshow': Mock(),
            'waitKey': Mock(side_effect=keys),
            'getWindowProperty': Mock(side_effect=visibility),
            'destroyAllWindows': Mock(),
        }
        with patch.object(run_camera, 'EARLivenessDetector', return_value=detector), \
                patch.multiple(run_camera.cv2, **gui), \
                patch.object(sys, 'stdout', new_callable=io.StringIO) as stdout:
            yield detector, gui, stdout

    def test_nonfinite_seconds_rejected_before_resources_are_initialized(self):
        for seconds in ('nan', 'inf', '-inf'):
            with self.subTest(seconds=seconds), \
                    patch.object(run_camera, 'EARLivenessDetector', side_effect=AssertionError('Model initialized')), \
                    patch.object(run_camera.cv2, 'VideoCapture', side_effect=AssertionError('Capture initialized')), \
                    patch.object(run_camera.cv2, 'destroyAllWindows'), \
                    patch.object(sys, 'stderr', new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit) as error:
                    run_camera.main(['--headless', f'--seconds={seconds}'])
                self.assertEqual(error.exception.code, 2)
                self.assertIn('Resolusi/batas durasi atau frame tidak valid', stderr.getvalue())

    def test_processing_samples_are_not_retained_for_the_entire_run(self):
        class ProcessingSample(float):
            pass

        samples = []
        frame = np.zeros((8, 8, 3), dtype=np.uint8)

        def process_frame(frame, timestamp):
            self.assertTrue(all(sample() is None for sample in samples[:-1]),
                            'Prior processing samples must not accumulate with frame count')
            sample = ProcessingSample((len(samples) + 1) * 4)
            samples.append(weakref.ref(sample))
            return frame, {'face_detected': False, 'total_blinks': 0, 'processing_ms': sample}

        detector = Mock()
        detector.get_state.return_value = {'backend': 'mocked'}
        detector.process_frame.side_effect = process_frame
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, frame)
        with patch.object(run_camera, 'EARLivenessDetector', return_value=detector), \
                patch.object(run_camera.cv2, 'VideoCapture', return_value=capture), \
                patch.object(sys, 'stdout', new_callable=io.StringIO) as stdout:
            result = run_camera.main(['--headless', '--max-frames', '4'])
        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue()[stdout.getvalue().index('{'):])
        self.assertEqual(report['frames_processed'], 4)
        self.assertEqual(report['mean_inference_and_ear_ms'], sum((4, 8, 12, 16)) / 4)
        capture.release.assert_called_once_with()
        detector.close.assert_called_once_with()

    def test_static_preview_waits_for_dismissal_or_seconds_without_reprocessing(self):
        cases = (
            ('q', [-1, -1, ord('q')], [1, 1], []),
            ('Q', [-1, -1, ord('Q')], [1, 1], []),
            ('escape', [-1, -1, 27], [1, 1], []),
            ('window_close', [-1, -1, -1], [1, 1, 0], []),
            ('seconds', [-1, -1, -1], [1, 1, 1], ['--seconds', '0.5']),
        )
        for name, keys, visibility, limit in cases:
            with self.subTest(exit_reason=name), self._mocked_static_image(keys, visibility) as (detector, gui, stdout), \
                    patch.object(run_camera.time, 'perf_counter', side_effect=[0.0, 0.0, 0.1, 0.2, 0.5, 0.6]):
                self.assertEqual(run_camera.main(['--image', 'mocked.png', *limit]), 0)
                self.assertEqual(gui['waitKey'].call_count, 3,
                                 'Static preview must remain open past its first GUI poll')
                detector.process_frame.assert_called_once()
                detector.close.assert_called_once_with()
                gui['destroyAllWindows'].assert_called_once_with()
                gui['VideoCapture'].assert_not_called()
                gui['imwrite'].assert_not_called()
                report = json.loads(stdout.getvalue()[stdout.getvalue().index('{'):])
                self.assertEqual(report['frames_processed'], 1)
                self.assertEqual(report['observed_total_blinks'], 0)

    def test_headless_static_image_processes_once_without_gui_or_automatic_files(self):
        with self._mocked_static_image([], []) as (detector, gui, stdout):
            self.assertEqual(run_camera.main(['--image', 'mocked.png', '--headless']), 0)
        detector.process_frame.assert_called_once()
        detector.close.assert_called_once_with()
        for name in ('VideoCapture', 'imwrite', 'namedWindow', 'resizeWindow', 'imshow',
                     'waitKey', 'getWindowProperty', 'destroyAllWindows'):
            gui[name].assert_not_called()
        report = json.loads(stdout.getvalue()[stdout.getvalue().index('{'):])
        self.assertEqual(report['frames_processed'], 1)

    def test_static_preview_reset_does_not_reprocess_image(self):
        with self._mocked_static_image([ord('r'), -1, ord('q')], [1, 1]) as (detector, gui, stdout):
            self.assertEqual(run_camera.main(['--image', 'mocked.png']), 0)
        detector.reset_verification.assert_called_once_with()
        detector.process_frame.assert_called_once()
        self.assertEqual(gui['waitKey'].call_count, 3)
        detector.close.assert_called_once_with()
        gui['destroyAllWindows'].assert_called_once_with()

    def test_negative_seconds_rejected_before_model_initialization(self):
        with patch.object(run_camera, 'EARLivenessDetector', side_effect=AssertionError('Model initialized')), \
                patch.object(run_camera.cv2, 'VideoCapture', side_effect=AssertionError('Capture initialized')), \
                patch.object(sys, 'stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:
                run_camera.main(['--headless', '--seconds=-0.5'])
        self.assertEqual(error.exception.code, 2)

    def test_zero_seconds_is_not_a_headless_capture_bound(self):
        with patch.object(run_camera, 'EARLivenessDetector', side_effect=AssertionError('Model initialized')), \
                patch.object(run_camera.cv2, 'VideoCapture', side_effect=AssertionError('Capture initialized')), \
                patch.object(sys, 'stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:
                run_camera.main(['--headless', '--seconds', '0'])
        self.assertEqual(error.exception.code, 2)

    def test_importing_vision_does_not_import_audio_worker(self):
        result = subprocess.run(
            [sys.executable, '-c', "import sys; from ml_engine.vision_ear import EARLivenessDetector; assert 'ml_engine.audio_siren' not in sys.modules, 'Vision import menarik audio'; assert 'sklearn' not in sys.modules"],
            cwd=BASE, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_headless_image_creates_actual_overlay_and_report(self):
        runner = BASE / 'run_camera.py'
        self.assertTrue(runner.is_file(), 'Belum ada runner kamera yang bisa dijalankan')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as folder:
            root = Path(folder)
            image = root / 'blank.png'
            output = root / 'annotated.jpg'
            report = root / 'report.json'
            self.assertTrue(cv2.imwrite(str(image), np.zeros((480, 640, 3), np.uint8)))
            result = subprocess.run(
                [sys.executable, str(runner), '--image', str(image), '--headless',
                 '--snapshot', str(output), '--report', str(report)],
                cwd=BASE, text=True, capture_output=True, timeout=45,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(cv2.imread(str(output)).shape, (480, 980, 3))
            data = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(data['frames_processed'], 1)
            self.assertFalse(data['last_state']['face_detected'])
            self.assertFalse(data['last_state']['authorized'])


if __name__ == '__main__':
    unittest.main()
