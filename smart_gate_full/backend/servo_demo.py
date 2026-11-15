"""Explicit bench-only servo trigger; identity authorization is never inferred."""
import math
import threading


class OpenEyeGate:
    def __init__(self, seconds=5.0, max_gap=0.30):
        if not math.isfinite(seconds) or seconds <= 0 or not math.isfinite(max_gap) or max_gap <= 0:
            raise ValueError('Durasi/gap harus finite dan positif')
        self.seconds = seconds
        self.max_gap = max_gap
        self.started = self.previous_at = None
        self.fired = False
        self.elapsed = 0.0
        self.reason = 'MENUNGGU WAJAH'
        self.previous_bbox = None

    def reset_count(self, reason='MENUNGGU WAJAH'):
        self.started = None
        self.elapsed = 0.0
        self.reason = reason

    def update(self, state, frame_at, *, now):
        if self.fired:
            return False
        if frame_at is None or not math.isfinite(frame_at) or not math.isfinite(now):
            self.reset_count('FRAME TIDAK VALID')
            return False
        if frame_at > now or now - frame_at > self.max_gap:
            self.reset_count('FRAME BASI')
            return False
        if self.previous_at is not None:
            if frame_at <= self.previous_at:
                if frame_at < self.previous_at:
                    self.reset_count('WAKTU FRAME MUNDUR')
                return False
            if frame_at - self.previous_at > self.max_gap:
                self.reset_count('TRACKING TERPUTUS')
        self.previous_at = frame_at
        if state.get('capture_error') or not state.get('face_detected'):
            self.previous_bbox = None
            self.reset_count('MENUNGGU WAJAH')
            return False
        bbox = state.get('face_bbox')
        if bbox is not None:
            if len(bbox) != 4 or not all(math.isfinite(v) for v in bbox):
                self.reset_count('KOTAK WAJAH INVALID')
                return False
            if self.previous_bbox is not None:
                old = self.previous_bbox
                old_size = max(old[2] - old[0], old[3] - old[1], 1)
                new_size = max(bbox[2] - bbox[0], bbox[3] - bbox[1], 1)
                shift = math.hypot((old[0] + old[2] - bbox[0] - bbox[2]) / 2,
                                   (old[1] + old[3] - bbox[1] - bbox[3]) / 2)
                if shift > 0.65 * old_size or not .55 <= new_size / old_size <= 1.8:
                    self.reset_count('WAJAH BERPINDAH')
            self.previous_bbox = list(bbox)
        if state.get('left_eye_state') != 'TERBUKA' or state.get('right_eye_state') != 'TERBUKA':
            self.reset_count('KEDUA MATA HARUS TERBUKA')
            return False
        if self.started is None:
            self.started = frame_at
        self.elapsed = frame_at - self.started
        self.reason = 'HITUNGAN'
        if self.elapsed >= self.seconds:
            self.fired = True
            self.reason = 'EVENT BUKA'
            return True
        return False

    def snapshot(self):
        return {'elapsed_seconds': round(self.elapsed, 2), 'required_seconds': self.seconds,
                'fired': self.fired, 'reason': self.reason}


class ServoController:
    """Receive each processed frame exactly once; GET/HTTP never drives time."""
    def __init__(self, link=None):
        self.gate = OpenEyeGate()
        self.link = link
        self.lock = threading.RLock()
        self.blocked = False
        self.last_arm = float('-inf')
        self.event = 'MENUNGGU'
        self.ready_since = None

    def tick(self, now):
        with self.lock:
            if self.link is None:
                if not self.gate.fired and self.gate.previous_at is not None and now - self.gate.previous_at > self.gate.max_gap:
                    self.gate.reset_count('FRAME BASI')
                return
            self.link.poll(now)
            if self.link.error:
                self.blocked = True
                if not self.gate.fired:
                    self.gate.reset_count('KONEKSI ERROR')
                self.event = self.link.error
                return
            if self.blocked:
                return
            if self.link.state == 0 and now - self.last_arm >= .5:
                if self.link.arm(now):
                    self.last_arm = now
                    self.event = 'ARM DIKIRIM: TARGET AWAL 90'
            self.link.keepalive(now)
            if self.link.ready(now):
                if self.ready_since is None:
                    self.ready_since = now
            elif not self.gate.fired:
                self.ready_since = None
            if not self.gate.fired and (not self.link.ready(now) or
                    self.gate.previous_at is None or now - self.gate.previous_at > self.gate.max_gap):
                self.gate.reset_count('MENUNGGU ARM / FRAME BARU')

    def on_frame(self, state, frame_at, *, now):
        with self.lock:
            if self.blocked:
                return False
            if self.link is not None and not self.link.ready(now):
                if not self.gate.fired:
                    self.gate.reset_count('MENUNGGU ARM')
                return False
            if self.link is not None:
                if self.ready_since is None:
                    self.ready_since = now
                if frame_at is None or frame_at < self.ready_since:
                    self.gate.reset_count('MENUNGGU FRAME SETELAH ARM')
                    return False
            fired = self.gate.update(state, frame_at, now=now)
            if fired:
                if self.link is None:
                    self.event = 'SIMULASI: EVENT BUKA SEKALI'
                elif self.link.open_once(now):
                    self.event = 'OPEN DIKIRIM; TUNGGU ACK, POSISI BELUM DIUKUR'
                else:
                    self.blocked = True
                    self.event = 'OPEN TIDAK TERKIRIM; MULAI ULANG SESI'
            return fired

    def snapshot(self):
        with self.lock:
            return {'mode': 'SIMULASI TANPA GERAK' if self.link is None else 'DEMO HARDWARE AKTIF',
                    'gate': self.gate.snapshot(), 'event': self.event,
                    'link': None if self.link is None else self.link.snapshot(),
                    'blocked': self.blocked, 'authorized': False}
