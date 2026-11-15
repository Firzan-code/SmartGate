"""Reuse the existing camera/model; forward only newly processed frames."""
import time
import cv2
from .camera import LaptopVision


class ServoVision(LaptopVision):
    def __init__(self, controller, camera_index=0, backend='dshow'):
        self.controller = controller
        super().__init__(camera_index=camera_index, backend=backend)

    def _invalidate_capture_locked(self, error):
        super()._invalidate_capture_locked(error)
        # A failed read breaks continuity even if the next read is <300ms later.
        with self.controller.lock:
            if not self.controller.gate.fired:
                self.controller.gate.reset_count('KAMERA ERROR')
                self.controller.gate.previous_bbox = None

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
                # Conservative read-start boundary survives a scheduling pause
                # after read() and also includes time blocked inside the driver.
                captured_at = time.monotonic()
                ok, frame = capture.read()
                if ok and frame is not None:
                    self.process_frame(frame, captured_at=captured_at)
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

    def process_frame(self, frame_bgr, timestamp=None, *, captured_at=None):
        annotated, state = super().process_frame(frame_bgr, timestamp=timestamp)
        # Missing acquisition provenance must not be replaced with inference time.
        self.controller.on_frame(state, captured_at, now=time.monotonic())
        return annotated, state
