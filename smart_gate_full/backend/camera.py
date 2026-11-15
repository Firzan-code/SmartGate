"""Select a laptop capture backend while preserving the existing EAR implementation."""
import time
import cv2
from ml_engine.vision_ear import EARLivenessDetector


class LaptopVision(EARLivenessDetector):
    def __init__(self, camera_index=0, backend='dshow'):
        self.capture_backend = {'auto': cv2.CAP_ANY, 'dshow': cv2.CAP_DSHOW,
                                'msmf': cv2.CAP_MSMF}[backend]
        super().__init__(camera_index=camera_index)

    def _camera_loop(self):
        capture = None
        try:
            capture = cv2.VideoCapture(self.camera_index, self.capture_backend)
            if not capture.isOpened():
                raise RuntimeError('Webcam tidak dapat dibuka; cek izin, indeks, atau --backend')
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            capture.set(cv2.CAP_PROP_FPS, 30)
            while self._running:
                ok, frame = capture.read()
                if ok and frame is not None:
                    self.process_frame(frame)
                else:
                    with self._lock:
                        self._invalidate_capture_locked('Pembacaan webcam gagal')
                    time.sleep(.05)
        except Exception as exc:
            with self._lock:
                self._invalidate_capture_locked(f'{type(exc).__name__}: {exc}')
        finally:
            self._running = False
            if capture is not None:
                capture.release()
