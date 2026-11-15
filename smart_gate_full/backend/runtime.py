"""Shared observation state. No serial-port ownership and no gate actuation."""
from collections import deque
from copy import deepcopy
import queue
import socket
import threading
import time

from .protocol import decode_audio_packet
from .stream import AudioStream


def serial_summary(state):
    v, a = state['vision'], state['audio']
    face = ('TERDETEKSI' if v.get('face_detected') else 'TIDAK_TERDETEKSI') if v['status'] == 'live' else v['status'].upper()
    eyes = f"{v.get('left_eye_state', '-')}/{v.get('right_eye_state', '-')}" if v['status'] == 'live' else '-/-'
    ear = f"{v.get('ear_left', 0):.3f}/{v.get('ear_right', 0):.3f}" if v['status'] == 'live' else '-/-'
    sound = ('SIRENE' if a.get('siren_detected') else 'NON_SIRENE') if a['status'] == 'live' else {'waiting': 'MENUNGGU', 'buffering': 'BUFFERING', 'stale': 'BASI', 'error': 'ERROR'}.get(a['status'], 'ERROR')
    prob = f"{a['siren_probability']:.2f}" if a.get('siren_probability') is not None else '-'
    return (f"WAJAH={face} MATA_L/R={eyes} EAR_L/R={ear} "
            f"KEDIP={v.get('total_blinks', 0)} SUARA={sound} P={prob} SUMBER=MAX9814 IDENTITAS=BELUM_DIVERIFIKASI")


class MonitorRuntime:
    def __init__(self):
        self._lock = threading.RLock()
        self._stream = AudioStream()
        self._events = deque(maxlen=40)
        self._audio = {'status': 'waiting', 'source': 'MAX9814_ESP32',
                       'siren_detected': None, 'siren_probability': None, 'consecutive_hits': 0,
                       'spectrum_freqs_hz': [], 'spectrum_magnitudes': [], 'error': None,
                       'adc_min': None, 'adc_max': None, 'adc_avg': None, 'adc_p2p': None,
                       'inference_ms': None}
        self._vision = {'status': 'waiting', 'face_detected': False,
                        'left_eye_state': 'TIDAK_TERDETEKSI', 'right_eye_state': 'TIDAK_TERDETEKSI',
                        'ear_left': None, 'ear_right': None, 'ear_avg': None,
                        'blink_counter': 0, 'total_blinks': 0, 'liveness_verified': False, 'error': None}
        self._audio_at = None
        self._audio_generation = None
        self._transport_error = None
        self._detector = None
        self._udp_port = 5006
        self._socket = None
        self._threads = []
        self._stop = threading.Event()
        self._pending = queue.Queue(maxsize=1)
        self._classifier = None
        self._started = False
        self._used = False
        self._camera_enabled = False
        self._last_sent = 0.
        self._last_line = None
        self._event('Server siap; menunggu audio MAX9814 dari ESP32-S3')

    def _event(self, text):
        self._events.append({'time': time.strftime('%H:%M:%S'), 'message': str(text)[:300]})

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            transport = self._stream.snapshot(now)
            transport['udp_port'] = self._udp_port
            vision = deepcopy(self._vision)
            if self._detector is not None:
                v = self._detector.get_state()
                vision.update(v)
                vision['error'] = v.get('capture_error')
                vision['status'] = 'error' if vision['error'] else 'live' if 'eye_state' in v else 'waiting'
            audio = deepcopy(self._audio)
            if audio['status'] != 'error':
                status = transport['status']
                if status in ('waiting', 'stale'):
                    audio['status'] = status
                elif self._audio_generation != self._stream.generation or self._audio_at is None:
                    audio['status'] = 'buffering'
                elif now - self._audio_at > 1.5:
                    audio['status'] = 'stale'
                if audio['status'] != 'live':
                    audio.update(siren_detected=None, siren_probability=None, consecutive_hits=0,
                                 spectrum_freqs_hz=[], spectrum_magnitudes=[])
            state = {'vision': vision, 'audio': audio, 'transport': transport,
                     'events': list(self._events), 'authorized': False}
            state['serial_line'] = serial_summary(state)
            return state

    def start(self, camera_enabled=True, camera_index=0, udp_host='0.0.0.0', udp_port=5006,
              classifier=None, camera_backend='dshow'):
        if self._started:
            raise RuntimeError('Runtime sudah berjalan')
        if self._used:
            raise RuntimeError('Buat runtime baru untuk mulai ulang')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256 * 1024)
            sock.bind((udp_host, udp_port))
            sock.settimeout(.05)
        except Exception:
            sock.close()
            raise
        self._socket = sock
        self._udp_port = sock.getsockname()[1]
        self._stop.clear()
        self._started = True
        self._used = True
        self._camera_enabled = camera_enabled
        if classifier is not None:
            self._classifier = classifier
        else:
            try:
                from .audio_model import AudioClassifier
                self._classifier = AudioClassifier()
            except Exception as exc:
                self._audio_error(f'{type(exc).__name__}: {exc}')
        jobs = [('audio-network', self._receive_loop), ('audio-inference', self._infer_loop)]
        if camera_enabled:
            jobs.append(('vision-init', lambda: self._start_camera(camera_index, camera_backend)))
        else:
            self._vision.update(status='error', error='Kamera dinonaktifkan (--no-camera)')
        for name, target in jobs:
            thread = threading.Thread(name=name, target=target, daemon=True)
            self._threads.append(thread)
            thread.start()

    def _start_camera(self, index, backend):
        detector = None
        try:
            from .camera import LaptopVision
            detector = LaptopVision(camera_index=index, backend=backend)
            if self._stop.is_set():
                detector.close()
                return
            with self._lock:
                self._detector = detector
                self._event('Model kamera siap; mulai webcam laptop (tanpa rekaman)')
            detector.start()
        except Exception as exc:
            with self._lock:
                self._vision.update(status='error', error=f'{type(exc).__name__}: {exc}')
                self._event(f"Kamera error: {self._vision['error']}")
            if detector is not None:
                detector.close()
                with self._lock:
                    self._detector = None

    def _audio_error(self, error, *, terminal=False):
        with self._lock:
            if terminal:
                self._transport_error = error
                self._stream._reset()
                self._audio_at = self._audio_generation = None
                while True:
                    try:
                        self._pending.get_nowait()
                    except queue.Empty:
                        break
            elif self._transport_error is not None:
                return
            self._audio.update(status='error', error=error, siren_detected=None,
                               siren_probability=None, consecutive_hits=0,
                               spectrum_freqs_hz=[], spectrum_magnitudes=[])
            self._event(f'Audio error: {error}')

    def _receive_loop(self):
        while not self._stop.is_set():
            try:
                raw, peer = self._socket.recvfrom(65535)  # Validate the complete UDP datagram.
                now = time.monotonic()
                try:
                    packet = decode_audio_packet(raw)
                except ValueError:
                    with self._lock:
                        self._stream.rejected += 1
                    continue
                with self._lock:
                    previous = self._stream.packets
                    window = self._stream.push(packet, peer, now)
                    if previous == 0 and self._stream.packets:
                        self._event(f'Audio terhubung dari {peer[0]}:{peer[1]}')
                if window is not None and self._classifier is not None:
                    try:
                        self._pending.put_nowait(window)
                    except queue.Full:
                        try:
                            self._pending.get_nowait()
                        except queue.Empty:
                            pass
                        self._pending.put_nowait(window)
            except socket.timeout:
                pass
            except OSError as exc:
                if not self._stop.is_set():
                    self._audio_error(f'UDP gagal: {exc}', terminal=True)
                break
            self._send_result()

    def _send_result(self):
        now = time.monotonic()
        state = self.snapshot(now)
        with self._lock:
            peer = self._stream.peer
            age = state['transport']['seconds_since_packet']
        if peer is None or age is None or age > 3 or now - self._last_sent < .25:
            return
        line = state['serial_line']
        try:
            self._socket.sendto(('SGR1 ' + line).encode('ascii', errors='replace')[:512], peer)
            self._last_sent = now
            if line != self._last_line:
                self._last_line = line
                with self._lock:
                    self._event(line)
        except OSError as exc:
            with self._lock:
                self._event(f'Gagal mengirim hasil ke ESP: {exc}')

    def _infer_loop(self):
        while not self._stop.is_set():
            try:
                window = self._pending.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                result = self._classifier.predict(window)
                self._publish_audio(window, result)
            except Exception as exc:
                self._audio_error(f'{type(exc).__name__}: {exc}')

    def _publish_audio(self, window, result, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            if (self._transport_error is not None or window.generation != self._stream.generation
                    or now - window.received_at > 1.5):
                return False
            self._audio = result
            self._audio_generation = window.generation
            self._audio_at = window.received_at
            return True

    def get_jpeg(self):
        with self._lock:
            detector = self._detector
        return None if detector is None else detector.get_jpeg_frame()

    def stop(self):
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        for thread in self._threads:
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError(f'Worker belum berhenti: {thread.name}')
        if self._detector is not None:
            self._detector.close()
            self._detector = None
        self._started = False
