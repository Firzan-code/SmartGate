"""State machine EAR berbasis timestamp, tanpa kamera atau pengenal identitas."""
from collections import deque
import math


class BlinkStateMachine:
    """Hitung buka -> tutup -> buka dari kedua mata dalam satu aliran waktu."""

    def __init__(self, ear_threshold=0.21, open_threshold=0.25,
                 required_blinks=2, blink_window_sec=5.0,
                 min_closed_sec=0.05, max_closed_sec=0.40,
                 verified_hold_sec=3.0, max_tracking_gap_sec=0.30):
        values = (ear_threshold, open_threshold, blink_window_sec, min_closed_sec,
                  max_closed_sec, verified_hold_sec, max_tracking_gap_sec)
        if (not all(math.isfinite(v) and v > 0 for v in values)
                or ear_threshold >= open_threshold or min_closed_sec >= max_closed_sec
                or not isinstance(required_blinks, int) or required_blinks < 1):
            raise ValueError('Parameter ambang/durasi tidak valid')
        self.ear_threshold = ear_threshold
        self.open_threshold = open_threshold
        self.required_blinks = required_blinks
        self.blink_window_sec = blink_window_sec
        self.min_closed_sec = min_closed_sec
        self.max_closed_sec = max_closed_sec
        self.verified_hold_sec = verified_hold_sec
        self.max_tracking_gap_sec = max_tracking_gap_sec
        self.blink_times = deque()
        self.closed_since = None
        self.verified_until = None
        self.total_blinks = 0
        self.armed = False
        self.last_timestamp = None

    def reset(self):
        self.blink_times.clear()
        self.closed_since = None
        self.verified_until = None
        self.armed = False

    def update(self, ear_left, ear_right, timestamp, face_detected=True):
        now = float(timestamp)
        if not math.isfinite(now):
            raise ValueError('Timestamp harus finite')
        if self.last_timestamp is not None and now <= self.last_timestamp:
            raise ValueError('Timestamp harus naik monoton')
        if face_detected and any(not math.isfinite(v) or v < 0 for v in (ear_left, ear_right)):
            raise ValueError('EAR harus finite dan tidak negatif')
        if self.last_timestamp is not None and now - self.last_timestamp > self.max_tracking_gap_sec:
            self.reset()
        self.last_timestamp = now
        if self.verified_until is not None and now >= self.verified_until:
            self.reset()
        if not face_detected:
            self.reset()
            return {
                'face_detected': False, 'blink_counter': 0, 'total_blinks': self.total_blinks,
                'closed_duration_ms': 0.0, 'liveness_verified': False,
                'authorized': False, 'trigger_reason': 'STANDBY',
            }
        both_closed = ear_left < self.ear_threshold and ear_right < self.ear_threshold
        both_open = ear_left >= self.open_threshold and ear_right >= self.open_threshold
        duration = 0.0
        if both_closed and self.armed and self.closed_since is None:
            self.closed_since = now
        if self.closed_since is not None:
            duration = now - self.closed_since
            # Buka satu mata membatalkan siklus bilateral; jangan mengambil
            # durasi menunggu mata satunya sebagai bukti penutupan keduanya.
            if not both_open and (ear_left >= self.open_threshold or ear_right >= self.open_threshold):
                self.closed_since = None
                self.armed = False
                duration = 0.0
        if both_open and self.closed_since is not None:
            if self.min_closed_sec <= duration <= self.max_closed_sec:
                self.blink_times.append(now)
                self.total_blinks += 1
            self.closed_since = None
        if both_open:
            self.armed = True
        while self.blink_times and now - self.blink_times[0] > self.blink_window_sec:
            self.blink_times.popleft()
        if self.verified_until is None and len(self.blink_times) >= self.required_blinks:
            self.verified_until = now + self.verified_hold_sec
        verified = self.verified_until is not None and now < self.verified_until
        return {
            'face_detected': bool(face_detected),
            'blink_counter': len(self.blink_times), 'total_blinks': self.total_blinks,
            'closed_duration_ms': round(duration * 1000, 1),
            'liveness_verified': verified, 'authorized': False,
            'trigger_reason': 'EAR_LIVENESS_VERIFIED' if verified else 'STANDBY',
        }
