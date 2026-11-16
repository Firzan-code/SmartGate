"""AST ONNX classifier over continuous three-second MAX9814 audio."""
import time

import numpy as np

from ml_engine.ast_siren import ASTSirenModel
from ml_engine.train_siren_model import compute_stft_frames


class AudioClassifier:
    window_samples = 48000
    hop_packets = 150
    max_result_age_sec = 5.0

    def __init__(self, model_path=None, ast_model=None):
        self.model = ast_model or ASTSirenModel(model_path)
        self._generation = self._sequence = None
        self._hits = 0

    def _base_result(self, window, status):
        raw = np.asarray(window.samples)
        return {
            "status": status,
            "source": "MAX9814_ESP32",
            "siren_probability": None,
            "siren_detected": None,
            "consecutive_hits": 0,
            "error": None,
            "spectrum_freqs_hz": [],
            "spectrum_magnitudes": [],
            "inference_ms": None,
            "adc_min": window.adc_min,
            "adc_max": window.adc_max,
            "adc_avg": round(window.adc_avg, 1),
            "adc_p2p": window.adc_max - window.adc_min,
            "clipped": bool(raw.min() <= 10 or raw.max() >= 4085),
            "model_name": "siren_ast_v2",
            "model_note": "AST ONNX 3 detik; validasi suara lapangan tetap diperlukan",
        }

    def predict(self, window):
        started = time.perf_counter()
        raw = np.asarray(window.samples)
        if raw.shape != (self.window_samples,) or not np.isfinite(raw).all() or raw.min() < 0 or raw.max() > 4095:
            raise ValueError("Inferensi AST memerlukan tiga detik ADC valid 16 kHz")

        contiguous = (
            self._generation == window.generation
            and self._sequence is not None
            and ((window.sequence - self._sequence) & 0xFFFFFFFF) == self.hop_packets
        )
        if not contiguous:
            self._hits = 0
        self._generation, self._sequence = window.generation, window.sequence
        clip = (raw.astype(np.float32) - np.float32(raw.mean())) / np.float32(2048.0)
        result = self._base_result(window, "live")
        prediction = self.model.predict(clip)
        probabilities = prediction["all_probabilities"]
        siren_probability = float(probabilities.get("ambulance", 0.0) + probabilities.get("other_siren", 0.0))
        if not np.isfinite(siren_probability) or not 0 <= siren_probability <= 1:
            raise ValueError("Probabilitas sirene AST invalid")
        self._hits = min(2, self._hits + 1) if siren_probability >= 0.80 else 0

        freqs, magnitude = compute_stft_frames(clip.astype(np.float64))
        mask = freqs <= 4000
        spectrum = magnitude.mean(axis=0)[mask][::4]
        spectrum = spectrum / max(float(spectrum.max()), 1e-9)
        result.update({
            "status": "live",
            "siren_probability": round(siren_probability, 4),
            "siren_detected": self._hits >= 2,
            "consecutive_hits": self._hits,
            "spectrum_freqs_hz": freqs[mask][::4].round(1).tolist(),
            "spectrum_magnitudes": spectrum.round(4).tolist(),
            "inference_ms": round((time.perf_counter() - started) * 1000, 2),
            "class_name": prediction["class_name"],
            "class_probability": round(float(prediction["probability"]), 4),
            "class_probabilities": {key: round(float(value), 4) for key, value in probabilities.items()},
            "model_buffer_samples": 48000,
        })
        return result
