"""MediaPipe FaceLandmarker + EAR dan overlay kamera lokal.

Enam titik per mata menghasilkan EAR geometris. Kedipan divalidasi memakai
waktu monoton oleh eye_blink.BlinkStateMachine, bukan jumlah frame.
Kotak/garis tidak memerlukan YOLO. Modul ini TIDAK mengenali identitas,
TIDAK membuka gerbang dan TIDAK mengklaim tahan serangan video replay.
process_frame harus dipanggil satu producer; get_state/get_jpeg_frame aman
untuk consumer lain. Semua input dan output kamera tetap lokal.
"""

import threading
import time
from collections import deque
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

try:
    from .eye_blink import BlinkStateMachine
except ImportError:
    from eye_blink import BlinkStateMachine

try:
    import mediapipe as mp
    HAS_MEDIAPIPE = True
except Exception:
    HAS_MEDIAPIPE = False

# Indeks Landmark Mata MediaPipe sesuai dokumen spesifikasi Bagian 1.2
LEFT_EYE_INDICES = [362, 385, 387, 263, 373, 380]
RIGHT_EYE_INDICES = [33, 160, 158, 133, 153, 144]

# Parameter Ambang Batas & State Machine sesuai dokumen Bagian 1.2 & 1.3
EAR_BLINK_THRESHOLD = 0.21
EAR_OPEN_THRESHOLD = 0.25
REQUIRED_BLINKS = 2
BLINK_WINDOW_SECONDS = 5.0

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
FACE_LANDMARKER_MODEL_PATH = MODELS_DIR / "face_landmarker.task"


def compute_ear(eye_points: np.ndarray) -> float:
    """
    Menghitung Eye Aspect Ratio (EAR) dari 6 titik landmark mata (p1..p6):
    EAR = (||p2 - p6|| + ||p3 - p5||) / (2 * ||p1 - p4||)
    """
    pts = np.asarray(eye_points, dtype=np.float64)
    if pts.shape != (6, 2):
        raise ValueError(f"eye_points harus berukuran (6, 2), diterima {pts.shape}")

    p1, p2, p3, p4, p5, p6 = pts
    vertical_1 = np.linalg.norm(p2 - p6)
    vertical_2 = np.linalg.norm(p3 - p5)
    horizontal = np.linalg.norm(p1 - p4)

    if horizontal < 1e-6:
        return 0.0
    return float((vertical_1 + vertical_2) / (2.0 * horizontal))


# Warna OpenCV memakai urutan BGR.
COLOR_WAITING = (0, 215, 255)
COLOR_VERIFIED = (80, 210, 80)
COLOR_EYE_WIDTH = (255, 200, 60)
COLOR_EYE_OPENING = (200, 80, 255)
PANEL_WIDTH = 340


def face_bounding_box(landmarks_xy: np.ndarray, frame_shape, padding: int = 12) -> Tuple[int, int, int, int]:
    """Kotak landmark dalam koordinat piksel, selalu dibatasi ukuran frame."""
    pts = np.asarray(landmarks_xy, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2 or not len(pts) or not np.isfinite(pts).all():
        raise ValueError("Landmark harus berupa koordinat finite N x 2")
    height, width = frame_shape[:2]
    lo = np.floor(pts.min(axis=0) - padding).astype(int)
    hi = np.ceil(pts.max(axis=0) + padding).astype(int)
    return (
        int(np.clip(lo[0], 0, width - 1)), int(np.clip(lo[1], 0, height - 1)),
        int(np.clip(hi[0], 0, width - 1)), int(np.clip(hi[1], 0, height - 1)),
    )


def draw_vision_overlay(frame_bgr: np.ndarray, landmarks_xy: Optional[np.ndarray], state: Dict) -> np.ndarray:
    """Gambar kotak, enam titik dan tiga ruas EAR per mata; panel di luar frame."""
    height, width = frame_bgr.shape[:2]
    canvas = np.full((max(height, 480), width + PANEL_WIDTH, 3), (24, 20, 18), dtype=np.uint8)
    canvas[:height, :width] = frame_bgr
    color = COLOR_VERIFIED if state.get("liveness_verified", False) else COLOR_WAITING
    if landmarks_xy is not None:
        pts = np.asarray(landmarks_xy)
        x1, y1, x2, y2 = face_bounding_box(pts, frame_bgr.shape)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        cv2.putText(canvas, "WAJAH | KEDIPAN", (x1, max(18, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
        for indices, label, ear_key in (
            (LEFT_EYE_INDICES, "L", "ear_left"), (RIGHT_EYE_INDICES, "R", "ear_right")
        ):
            eye = np.rint(pts[indices]).astype(np.int32)
            cv2.polylines(canvas, [eye], True, color, 1, cv2.LINE_AA)
            # p1-p4: lebar; p2-p6 dan p3-p5: bukaan kelopak.
            cv2.line(canvas, tuple(eye[0]), tuple(eye[3]), COLOR_EYE_WIDTH, 1)
            for a, b in ((1, 5), (2, 4)):
                cv2.line(canvas, tuple(eye[a]), tuple(eye[b]), COLOR_EYE_OPENING, 1)
            for point in eye:
                cv2.circle(canvas, tuple(point), 2, (245, 245, 245), -1)
            anchor = (max(0, int(eye[:, 0].min()) - 4), max(16, int(eye[:, 1].min()) - 12))
            cv2.putText(canvas, f"{label}: {state.get(ear_key, 0):.3f}", anchor,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.43, color, 1, cv2.LINE_AA)
    else:
        cv2.putText(canvas, "WAJAH TIDAK TERDETEKSI", (16, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_WAITING, 2, cv2.LINE_AA)

    x = width + 16
    cv2.line(canvas, (width, 0), (width, canvas.shape[0]), (80, 80, 80), 1)
    entries = [
        ("SMART GATE | VISION EAR", (240, 240, 240)),
        ("KEDIPAN TERPENUHI" if state.get("liveness_verified") else "MENUNGGU KEDIPAN", color),
        (f"Mata L: {state.get('left_eye_state', state.get('eye_state', '-'))}", (210, 210, 210)),
        (f"Mata R: {state.get('right_eye_state', state.get('eye_state', '-'))}", (210, 210, 210)),
        (f"EAR L: {state.get('ear_left', 0):.3f}   R: {state.get('ear_right', 0):.3f}", (240, 240, 240)),
        (f"EAR rata-rata: {state.get('ear_avg', 0):.3f}", (240, 240, 240)),
        (f"Tutup < {state.get('ear_threshold', 0.21):.2f} | Buka >= {state.get('open_threshold', 0.25):.2f}", (170, 170, 170)),
        (f"Kedipan (5 dtk): {state.get('blink_counter', 0)}/{state.get('required_blinks', 2)}", color),
        (f"Total kedipan: {state.get('total_blinks', 0)}", (210, 210, 210)),
        (f"Durasi tutup: {state.get('closed_duration_ms', 0):.0f} ms", (210, 210, 210)),
        (f"FPS: {state.get('fps', 0):.1f} | Infer: {state.get('processing_ms', 0):.1f} ms", (170, 170, 170)),
        ("Biru: lebar | Ungu: bukaan", COLOR_EYE_WIDTH),
        ("IDENTITAS BELUM DIVERIFIKASI", COLOR_WAITING),
        ("Bukan otorisasi / anti-replay", (170, 170, 170)),
        ("R: reset   Q / ESC: keluar", (170, 170, 170)),
    ]
    for index, (text, text_color) in enumerate(entries):
        cv2.putText(canvas, text, (x, 28 + index * 29),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.47, text_color, 1, cv2.LINE_AA)
    return canvas


class EARLivenessDetector:
    """
    Deteksi kedipan dengan satu producer frame dan consumer state/JPEG thread-safe.
    Memprioritaskan MediaPipe Tasks VIDEO; legacy FaceMesh jika masih tersedia.
    """

    def __init__(
        self,
        camera_index: int = 0,
        ear_threshold: float = EAR_BLINK_THRESHOLD,
        open_threshold: float = EAR_OPEN_THRESHOLD,
        required_blinks: int = REQUIRED_BLINKS,
        blink_window_sec: float = BLINK_WINDOW_SECONDS,
        smoothing_window: int = 2,
    ):
        self.camera_index = camera_index
        self.ear_threshold = ear_threshold
        self.open_threshold = open_threshold
        self.required_blinks = required_blinks
        self.blink_window_sec = blink_window_sec

        self._lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._closed = False
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._blink = BlinkStateMachine(
            ear_threshold=ear_threshold, open_threshold=open_threshold,
            required_blinks=required_blinks, blink_window_sec=blink_window_sec,
        )
        # State internal deteksi kedipan (State Machine Bagian 1.3)
        self._ear_history: deque = deque(maxlen=max(1, smoothing_window))
        self._latest_jpeg: Optional[bytes] = None
        self._previous_bbox = None
        self._last_model_timestamp_ms = -1
        self._frame_clock = None
        self._last_capture_clock = None
        # Freshness consumer memakai clock runtime, bukan timestamp video/simulasi.
        self._last_processed_monotonic = None

        # Inisialisasi backend MediaPipe Face Mesh / FaceLandmarker
        self._mp_mode = "NONE"
        self._landmarker = None
        self._face_mesh_legacy = None
        self._init_mediapipe()

        self._state: Dict = {
            "face_detected": False,
            "ear_left": 0.0,
            "ear_right": 0.0,
            "ear_avg": 0.0,
            "ear_smoothed": 0.0,
            "closed_duration_ms": 0.0,
            "face_bbox": None,
            "blink_counter": 0,
            "total_blinks": 0,
            "liveness_verified": False,
            "authorized": False,
            "face_identity": "BELUM_DIVERIFIKASI",
            "face_similarity": None,
            "trigger_reason": "STANDBY",
            "backend": self._mp_mode,
            "fps": 0.0,
            "updated_at": "-",
        }

    def _init_mediapipe(self) -> None:
        if not HAS_MEDIAPIPE:
            raise RuntimeError('MediaPipe tidak tersedia; install requirements_vision.txt')

        failure = f'Model tidak ditemukan: {FACE_LANDMARKER_MODEL_PATH}'
        # Prioritas 1: MediaPipe Tasks API (FaceLandmarker dengan model .task lokal)
        if hasattr(mp, "tasks") and FACE_LANDMARKER_MODEL_PATH.exists():
            try:
                from mediapipe.tasks import python as mp_python
                from mediapipe.tasks.python import vision as mp_vision

                base_options = mp_python.BaseOptions(
                    model_asset_path=str(FACE_LANDMARKER_MODEL_PATH)
                )
                options = mp_vision.FaceLandmarkerOptions(
                    base_options=base_options,
                    running_mode=mp_vision.RunningMode.VIDEO,
                    output_face_blendshapes=False,
                    output_facial_transformation_matrixes=False,
                    num_faces=1,
                    min_face_detection_confidence=0.5,
                    min_face_presence_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
                self._landmarker = mp_vision.FaceLandmarker.create_from_options(options)
                self._mp_mode = "MEDIAPIPE_TASKS_FACE_LANDMARKER"
                return
            except Exception as exc:
                failure = f'Gagal memuat {FACE_LANDMARKER_MODEL_PATH}: {exc}'
                self._landmarker = None

        # Prioritas 2: MediaPipe Solutions API (versi lama)
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh"):
            try:
                self._face_mesh_legacy = mp.solutions.face_mesh.FaceMesh(
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
                self._mp_mode = "MEDIAPIPE_SOLUTIONS_FACE_MESH"
                return
            except Exception as exc:
                failure += f'; backend legacy: {exc}'
                self._face_mesh_legacy = None
        raise RuntimeError(failure)

    def _extract_landmarks_xy(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Mengekstrak 468/478 titik koordinat wajah (x, y) dalam piksel."""
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        if self._mp_mode == "MEDIAPIPE_TASKS_FACE_LANDMARKER" and self._landmarker is not None:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            clock = time.monotonic() if self._frame_clock is None else self._frame_clock
            timestamp_ms = max(self._last_model_timestamp_ms + 1, int(clock * 1000))
            result = self._landmarker.detect_for_video(mp_image, timestamp_ms)
            self._last_model_timestamp_ms = timestamp_ms
            if result.face_landmarks and len(result.face_landmarks) > 0:
                face = result.face_landmarks[0]
                pts = np.array([[lm.x * w, lm.y * h] for lm in face], dtype=np.float64)
                return pts
            return None

        if self._mp_mode == "MEDIAPIPE_SOLUTIONS_FACE_MESH" and self._face_mesh_legacy is not None:
            result = self._face_mesh_legacy.process(rgb)
            if result.multi_face_landmarks:
                face = result.multi_face_landmarks[0].landmark
                pts = np.array([[lm.x * w, lm.y * h] for lm in face], dtype=np.float64)
                return pts
            return None

        return None

    def step_ear_state_machine(
        self, ear_left: float, ear_right: float,
        timestamp: Optional[float] = None,
        face_similarity=None, face_identity=None,
    ) -> Dict:
        """Dua kedipan berbasis waktu. Argumen identitas lama tidak memberi otorisasi."""
        now = time.monotonic() if timestamp is None else float(timestamp)
        with self._lock:
            result = self._blink.update(ear_left, ear_right, now)
            self._ear_history.append((ear_left + ear_right) / 2.0)
            self._state.update(result)
            self._last_processed_monotonic = time.monotonic()
            self._state.update({
                'ear_left': round(float(ear_left), 4),
                'ear_right': round(float(ear_right), 4),
                'ear_avg': round((ear_left + ear_right) / 2.0, 4),
                'ear_smoothed': round(float(np.mean(self._ear_history)), 4),
                'face_identity': 'BELUM_DIVERIFIKASI', 'face_similarity': None,
                'updated_at': time.strftime('%H:%M:%S'),
            })
            return dict(self._state)

    def register_face(self, name: str, frame_bgr: np.ndarray) -> bool:
        """Pengenalan identitas dinonaktifkan; fitur handmade lama bukan face recognition."""
        raise NotImplementedError('Pendaftaran identitas memerlukan modul face recognition terpisah')

    def process_frame(self, frame_bgr: np.ndarray, timestamp: Optional[float] = None) -> Tuple[np.ndarray, Dict]:
        """Landmark -> EAR -> kedipan -> kotak/garis/panel. Tidak mengotorisasi wajah."""
        if not isinstance(frame_bgr, np.ndarray) or frame_bgr.dtype != np.uint8 or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3 or min(frame_bgr.shape[:2]) < 1:
            raise ValueError("Frame harus berupa gambar BGR uint8 H x W x 3")
        t0 = time.perf_counter()
        self._frame_clock = time.monotonic() if timestamp is None else float(timestamp)
        landmarks = self._extract_landmarks_xy(frame_bgr)
        has_face = landmarks is not None and len(landmarks) > max(LEFT_EYE_INDICES + RIGHT_EYE_INDICES)
        if has_face:
            bbox = face_bounding_box(landmarks, frame_bgr.shape)
            previous = self._previous_bbox
            if previous is not None:
                old_center = np.array([(previous[0] + previous[2]) / 2, (previous[1] + previous[3]) / 2])
                new_center = np.array([(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2])
                old_size = max(previous[2] - previous[0], previous[3] - previous[1], 1)
                new_size = max(bbox[2] - bbox[0], bbox[3] - bbox[1], 1)
                if np.linalg.norm(new_center - old_center) > 0.65 * old_size or not 0.55 <= new_size / old_size <= 1.8:
                    self.reset_verification()
            self._previous_bbox = bbox
            ear_left = compute_ear(landmarks[LEFT_EYE_INDICES])
            ear_right = compute_ear(landmarks[RIGHT_EYE_INDICES])
            self.step_ear_state_machine(ear_left, ear_right, timestamp=self._frame_clock)
        else:
            self.reset_verification()
            ear_left = ear_right = 0.0
            bbox = None

        def eye_label(value):
            if not has_face:
                return "TIDAK_TERDETEKSI"
            if value < self.ear_threshold:
                return "TERTUTUP"
            return "TERBUKA" if value >= self.open_threshold else "TRANSISI"

        left_label, right_label = eye_label(ear_left), eye_label(ear_right)
        processing_ms = (time.perf_counter() - t0) * 1000.0
        elapsed = None if self._last_capture_clock is None else self._frame_clock - self._last_capture_clock
        fps = 0.0 if elapsed is None or elapsed <= 0 else 1.0 / elapsed
        self._last_capture_clock = self._frame_clock
        with self._lock:
            self._state.update({
                "face_detected": bool(has_face), "face_bbox": bbox,
                "ear_left": round(ear_left, 4), "ear_right": round(ear_right, 4),
                "ear_avg": round((ear_left + ear_right) / 2.0, 4),
                "left_eye_state": left_label, "right_eye_state": right_label,
                "eye_state": left_label if left_label == right_label else "TRANSISI",
                "authorized": False, "face_identity": "BELUM_DIVERIFIKASI", "face_similarity": None,
                "ear_threshold": self.ear_threshold, "open_threshold": self.open_threshold,
                "required_blinks": self.required_blinks,
                "processing_ms": round(processing_ms, 2),
                "fps": round(fps, 1), "capture_error": None,
            })
            self._last_processed_monotonic = time.monotonic()
            state = dict(self._state)
        annotated = draw_vision_overlay(frame_bgr, landmarks if has_face else None, state)
        ok, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        with self._lock:
            self._expire_capture_locked()
            if ok and self._last_processed_monotonic is not None:
                self._latest_jpeg = buf.tobytes()
        return annotated, state

    def _expire_capture_locked(self) -> None:
        if (self._last_processed_monotonic is not None
                and time.monotonic() - self._last_processed_monotonic > self._blink.max_tracking_gap_sec):
            self._invalidate_capture_locked('Capture tidak menghasilkan frame baru')

    def get_state(self) -> Dict:
        with self._lock:
            self._expire_capture_locked()
            return dict(self._state)

    def get_jpeg_frame(self) -> Optional[bytes]:
        with self._lock:
            self._expire_capture_locked()
            return self._latest_jpeg

    def _invalidate_capture_locked(self, error: str) -> None:
        """Buang hasil aktif tanpa mengubah timeline video atau total kedipan."""
        self._blink.reset()
        self._ear_history.clear()
        self._previous_bbox = None
        self._latest_jpeg = None
        self._last_processed_monotonic = None
        self._state.update({
            'face_detected': False, 'face_bbox': None,
            'ear_left': 0.0, 'ear_right': 0.0, 'ear_avg': 0.0, 'ear_smoothed': 0.0,
            'closed_duration_ms': 0.0, 'blink_counter': 0,
            'total_blinks': self._blink.total_blinks, 'liveness_verified': False,
            'eye_state': 'TIDAK_TERDETEKSI', 'left_eye_state': 'TIDAK_TERDETEKSI',
            'right_eye_state': 'TIDAK_TERDETEKSI', 'trigger_reason': 'STANDBY',
            'authorized': False, 'face_identity': 'BELUM_DIVERIFIKASI', 'face_similarity': None,
            'fps': 0.0, 'processing_ms': 0.0, 'capture_error': error,
        })

    def reset_verification(self) -> None:
        with self._lock:
            self._blink.reset()
            self._previous_bbox = None
            self._ear_history.clear()
            self._state["closed_duration_ms"] = 0.0
            self._state["ear_smoothed"] = 0.0
            self._state["blink_counter"] = 0
            self._state["liveness_verified"] = False
            self._state["trigger_reason"] = "STANDBY"

    def _camera_loop(self) -> None:
        cap = None
        try:
            cap = cv2.VideoCapture(self.camera_index)
            while self._running:
                ret, frame = cap.read()
                if ret and frame is not None:
                    self.process_frame(frame)
                else:
                    with self._lock:
                        self._invalidate_capture_locked('Pembacaan capture gagal')
                    time.sleep(0.05)
        except Exception as exc:
            with self._lock:
                self._invalidate_capture_locked(f'{type(exc).__name__}: {exc}')
            raise
        finally:
            self._running = False
            if cap is not None:
                cap.release()

    def close(self) -> None:
        """Hentikan capture; timeout membiarkan model hidup untuk retry close."""
        with self._lifecycle_lock:
            self.stop()
            if self._landmarker is not None:
                self._landmarker.close()
                self._landmarker = None
            if self._face_mesh_legacy is not None:
                self._face_mesh_legacy.close()
                self._face_mesh_legacy = None
            self._closed = True

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError('Detector sudah ditutup')
            if self._running:
                return
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError('Capture worker sebelumnya belum berhenti')
            self._running = True
            self._thread = threading.Thread(target=self._camera_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._running = False
            if self._thread is not None:
                self._thread.join(timeout=2.0)
                if self._thread.is_alive():
                    raise RuntimeError('Capture worker belum berhenti; model tetap hidup')


if __name__ == "__main__":
    print("=== Pengujian Modul 1: Vision EAR Liveness State Machine ===")
    detector = EARLivenessDetector()
    print(f"[INFO] Backend Aktif: {detector.get_state()['backend']}")

    # Hanya simulasi matematika, bukan hasil deteksi kamera manusia.
    open_eye = np.array([[0, 0], [10, 4.5], [20, 4.5], [30, 0], [20, -4.5], [10, -4.5]], dtype=float)
    closed_eye = np.array([[0, 0], [10, 2], [20, 2], [30, 0], [20, -2], [10, -2]], dtype=float)

    ear_open_val = compute_ear(open_eye)
    ear_closed_val = compute_ear(closed_eye)
    print(f"[MATH] EAR Mata Terbuka  = {ear_open_val:.4f} (Normal: 0.28 - 0.35)")
    print(f"[MATH] EAR Mata Berkedip = {ear_closed_val:.4f} (Ambang < 0.21)")

    # Simulasi 2 kedipan sah dalam 5 detik (masing-masing tertutup 4 frame lalu kembali terbuka)
    t_sim = time.monotonic()
    sequence = (
        [ear_open_val] * 3
        + [ear_closed_val] * 4  # Kedipan 1 (4 frame < 0.21)
        + [ear_open_val] * 4
        + [ear_closed_val] * 3  # Kedipan 2 (3 frame < 0.21)
        + [ear_open_val] * 2
    )
    for idx, ear_val in enumerate(sequence):
        st = detector.step_ear_state_machine(ear_val, ear_val, timestamp=t_sim + idx * 0.04)

    print(
        f"[STATE] Blink Counter (5s) = {st['blink_counter']} | "
        f"Liveness Verified = {st['liveness_verified']} | "
        f"Reason = {st['trigger_reason']}"
    )
    detector.close()
