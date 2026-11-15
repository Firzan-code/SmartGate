"""Reuse the local RF artifact on real incoming ADC windows; never auto-train."""
from pathlib import Path
import time
import joblib
import numpy as np

from ml_engine.train_siren_model import (MODEL_PATH, compute_stft_frames,
                                         extract_stft_mfcc_features)


class AudioClassifier:
    def __init__(self, model_path=None):
        path = Path(model_path) if model_path is not None else MODEL_PATH
        if not path.is_file():
            raise FileNotFoundError(f'Model audio tidak ditemukan: {path}')
        bundle = joblib.load(path)  # trusted, project-local artifact only
        self.model, self.scaler = bundle['model'], bundle['scaler']
        classes = list(self.model.classes_)
        self._siren_index = classes.index(1)
        if self.model.n_features_in_ != 30 or self.scaler.n_features_in_ != 30:
            raise ValueError('Model audio tidak cocok dengan kontrak 30 fitur')
        self._generation = self._sequence = None
        self._hits = 0

    def predict(self, window):
        started = time.perf_counter()
        raw = np.asarray(window.samples)
        if raw.shape != (16000,) or not np.isfinite(raw).all() or raw.min() < 0 or raw.max() > 4095:
            raise ValueError('Inferensi memerlukan satu detik ADC valid 16 kHz')
        signal = (raw.astype(np.float64) - raw.mean()) / 2048.
        features, summary = extract_stft_mfcc_features(signal)
        scaled = self.scaler.transform(features.reshape(1, -1))
        probability = float(self.model.predict_proba(scaled)[0, self._siren_index])
        if not np.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError('Model mengembalikan probabilitas invalid')
        if self._generation != window.generation or self._sequence is None or ((window.sequence - self._sequence) & 0xffffffff) != 25:
            self._hits = 0
        self._hits = min(2, self._hits + 1) if probability >= .80 else 0
        self._generation, self._sequence = window.generation, window.sequence
        freqs, mag = compute_stft_frames(signal)
        mask = freqs <= 4000
        spectrum = mag.mean(axis=0)[mask][::4]
        spectrum = spectrum / max(float(spectrum.max()), 1e-9)
        return {'status': 'live', 'source': 'MAX9814_ESP32',
                'siren_probability': round(probability, 4), 'siren_detected': self._hits >= 2,
                'consecutive_hits': self._hits, 'error': None,
                'spectrum_freqs_hz': freqs[mask][::4].round(1).tolist(),
                'spectrum_magnitudes': spectrum.round(4).tolist(),
                'inference_ms': round((time.perf_counter() - started) * 1000, 2),
                'adc_min': window.adc_min, 'adc_max': window.adc_max,
                'adc_avg': round(window.adc_avg, 1), 'adc_p2p': window.adc_max - window.adc_min,
                'clipped': bool(raw.min() <= 10 or raw.max() >= 4085),
                'ber_600_1800': round(summary['ber_mean'], 4),
                'model_note': 'Prototipe dilatih data sintetis; validasi mikrofon nyata belum selesai'}
