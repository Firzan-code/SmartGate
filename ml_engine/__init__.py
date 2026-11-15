"""
Smart Gate IoT - Multi-Modal Machine Learning Engine
====================================================
Modul 1: Computer Vision - Liveness Detection (EAR), tanpa verifikasi identitas (`vision_ear.py`)
Modul 2: Audio ML - Deteksi Sirene Darurat berbasis STFT & MFCC (`audio_siren.py`, `train_siren_model.py`)
"""

from .vision_ear import EARLivenessDetector, compute_ear

__all__ = [
    "EARLivenessDetector",
    "compute_ear",
    "SirenAudioDetector",
    "extract_stft_mfcc_features",
]


def __getattr__(name):
    """Vision tidak membutuhkan worker/dependensi audio saat di-import."""
    if name in {"SirenAudioDetector", "extract_stft_mfcc_features"}:
        from . import audio_siren
        return getattr(audio_siren, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
