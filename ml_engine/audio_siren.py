"""
Modul 2 (Real-Time Inference): Deteksi Sirene Darurat Berbasis STFT & MFCC
==========================================================================
Sesuai spesifikasi `rencana_pembuatan_machine_learning_smart_gate.md`:
- Menangkap aliran audio real-time pada fs = 16000 Hz secara non-blocking.
- Menghitung spektrum STFT (N=1024, H=512, Hann window) & 30 fitur (BER, 13 MFCC mu/sigma,
  Spectral Centroid, Pitch Modulation Variance).
- Memprediksi probabilitas sirene menggunakan Random Forest (`siren_rf_model.pkl`).
- Memicu status darurat (`SIREN_EMERGENCY`) jika Probabilitas Sirene >= 0.80
  selama 2 siklus berturut-turut.
"""

import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import numpy as np

try:
    from .train_siren_model import (
        MODEL_PATH,
        N_SAMPLES,
        SAMPLE_RATE,
        _generate_non_siren_sample,
        _generate_siren_sample,
        compute_stft_frames,
        extract_stft_mfcc_features,
        train_and_export_model,
    )
except ImportError:
    from train_siren_model import (
        MODEL_PATH,
        N_SAMPLES,
        SAMPLE_RATE,
        _generate_non_siren_sample,
        _generate_siren_sample,
        compute_stft_frames,
        extract_stft_mfcc_features,
        train_and_export_model,
    )

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False


class SirenAudioDetector:
    """
    Worker thread-safe untuk deteksi sirene darurat real-time (STFT + MFCC + Random Forest).
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        prob_threshold: float = 0.80,
        required_consecutive_hits: int = 2,
        step_interval_sec: float = 0.5,
    ):
        self.model_path = Path(model_path) if model_path else MODEL_PATH
        self.prob_threshold = prob_threshold
        self.required_consecutive_hits = required_consecutive_hits
        self.step_interval_sec = step_interval_sec

        # Pastikan model tersedia; jika belum ada, latih otomatis
        if not self.model_path.exists():
            train_and_export_model()

        bundle = joblib.load(self.model_path)
        self.model = bundle["model"]
        self.scaler = bundle["scaler"]
        self.feature_names = bundle["feature_names"]

        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._audio_buffer = np.zeros(N_SAMPLES, dtype=np.float64)
        self._consecutive_hits = 0
        self._simulation_mode: Optional[str] = None  # None | "siren" | "noise"

        # State yang dapat dibaca oleh Decision Engine & Web Dashboard
        self._state: Dict = {
            "siren_probability": 0.0,
            "siren_detected": False,
            "consecutive_hits": 0,
            "trigger_reason": "STANDBY",
            "ber_600_1800": 0.0,
            "spectral_centroid_hz": 0.0,
            "pitch_mod_std_hz": 0.0,
            "peak_freq_hz": 0.0,
            "inference_ms": 0.0,
            "spectrum_freqs_hz": [],
            "spectrum_magnitudes": [],
            "audio_source": "STANDBY",
            "updated_at": "-",
        }

    def predict_signal(self, signal: np.ndarray, source_label: str = "DIRECT") -> Dict:
        """
        Mengekstrak fitur STFT+MFCC dari sinyal 1 detik dan menjalankan inferensi Random Forest.
        """
        t0 = time.perf_counter()
        feat_vec, summary = extract_stft_mfcc_features(signal, fs=SAMPLE_RATE)
        feat_scaled = self.scaler.transform(feat_vec.reshape(1, -1))
        prob_siren = float(self.model.predict_proba(feat_scaled)[0, 1])
        inference_ms = (time.perf_counter() - t0) * 1000.0

        # Ambil spektrum rata-rata (downsampled ke 64 titik frekuensi 0 - 4000 Hz untuk grafik dashboard)
        freqs, mag = compute_stft_frames(signal, fs=SAMPLE_RATE)
        mean_mag = np.mean(mag, axis=0)
        max_freq_mask = freqs <= 4000.0
        freqs_sub = freqs[max_freq_mask]
        mag_sub = mean_mag[max_freq_mask]
        step = max(1, len(freqs_sub) // 64)
        spec_freqs = np.round(freqs_sub[::step], 1).tolist()
        spec_mags = np.round(mag_sub[::step] / (np.max(mag_sub) + 1e-9), 4).tolist()

        with self._lock:
            if prob_siren >= self.prob_threshold:
                self._consecutive_hits += 1
            else:
                self._consecutive_hits = 0

            is_emergency = self._consecutive_hits >= self.required_consecutive_hits
            self._state.update(
                {
                    "siren_probability": round(prob_siren, 4),
                    "siren_detected": bool(is_emergency),
                    "consecutive_hits": int(self._consecutive_hits),
                    "trigger_reason": "SIREN_EMERGENCY" if is_emergency else "STANDBY",
                    "ber_600_1800": round(summary["ber_mean"], 4),
                    "spectral_centroid_hz": round(summary["spectral_centroid_hz"], 1),
                    "pitch_mod_std_hz": round(summary["pitch_mod_std_hz"], 1),
                    "peak_freq_hz": round(summary["peak_freq_mean_hz"], 1),
                    "inference_ms": round(inference_ms, 3),
                    "spectrum_freqs_hz": spec_freqs,
                    "spectrum_magnitudes": spec_mags,
                    "audio_source": source_label,
                    "updated_at": time.strftime("%H:%M:%S"),
                }
            )
            return dict(self._state)

    def set_simulation_mode(self, mode: Optional[str]) -> None:
        """
        Mengaktifkan simulasi sinyal untuk pengujian tanpa mikrofon fisik:
        mode = 'siren' | 'noise' | None (mikrofon asli)
        """
        with self._lock:
            self._simulation_mode = mode

    def get_state(self) -> Dict:
        with self._lock:
            return dict(self._state)

    def _audio_callback(self, indata, frames, time_info, status):
        mono = indata[:, 0].astype(np.float64)
        with self._lock:
            if len(mono) >= N_SAMPLES:
                self._audio_buffer[:] = mono[-N_SAMPLES:]
            else:
                self._audio_buffer = np.roll(self._audio_buffer, -len(mono))
                self._audio_buffer[-len(mono) :] = mono

    def _worker_loop(self):
        rng = np.random.default_rng()
        stream = None

        if HAS_SOUNDDEVICE:
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    blocksize=int(SAMPLE_RATE * 0.25),
                    callback=self._audio_callback,
                )
                stream.start()
            except Exception:
                stream = None

        while self._running:
            with self._lock:
                sim_mode = self._simulation_mode
                buf_copy = self._audio_buffer.copy()

            if sim_mode == "siren":
                sig = _generate_siren_sample(rng, noisy=False)
                self.predict_signal(sig, source_label="SIMULATED_SIREN")
            elif sim_mode == "noise":
                sig = _generate_non_siren_sample(rng, noisy=True)
                self.predict_signal(sig, source_label="SIMULATED_ROAD_NOISE")
            elif stream is not None:
                self.predict_signal(buf_copy, source_label="MICROPHONE_LIVE")
            else:
                sig = _generate_non_siren_sample(rng, noisy=False) * 0.05
                self.predict_signal(sig, source_label="FALLBACK_IDLE")

            time.sleep(self.step_interval_sec)

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)


if __name__ == "__main__":
    detector = SirenAudioDetector()
    rng = np.random.default_rng(123)
    print("=== Pengujian Real-Time Inference Audio Sirene ===")
    for cycle in range(1, 3):
        siren_sig = _generate_siren_sample(rng, noisy=False)
        res = detector.predict_signal(siren_sig, source_label=f"TEST_SIREN_CYCLE_{cycle}")
        print(
            f"[Siklus {cycle} - SIRENE] Prob={res['siren_probability']:.4f} | "
            f"BER={res['ber_600_1800']:.3f} | PitchMod={res['pitch_mod_std_hz']:.1f} Hz | "
            f"Hits={res['consecutive_hits']} | Emergency={res['siren_detected']} ({res['trigger_reason']})"
        )
    noise_sig = _generate_non_siren_sample(rng, noisy=True)
    res_noise = detector.predict_signal(noise_sig, source_label="TEST_CAR_HORN_NOISE")
    print(
        f"[Siklus 3 - NON-SIRENE] Prob={res_noise['siren_probability']:.4f} | "
        f"BER={res_noise['ber_600_1800']:.3f} | PitchMod={res_noise['pitch_mod_std_hz']:.1f} Hz | "
        f"Hits={res_noise['consecutive_hits']} | Emergency={res_noise['siren_detected']}"
    )
