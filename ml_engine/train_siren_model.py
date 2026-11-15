"""
Modul 2 (Pelatihan): Pelatihan Model Klasifikasi Audio Sirene Darurat (STFT + MFCC)
===================================================================================
Sesuai spesifikasi `rencana_pembuatan_machine_learning_smart_gate.md`:
- Frekuensi Sampling (fs) : 16000 Hz
- Durasi Sampel           : 1.0 detik (16000 sampel)
- Ukuran Frame STFT (N)   : 1024 sampel (~64 ms)
- Hop Length (H)          : 512 sampel
- Fungsi Jendela          : Hann Window w[n] = 0.5 * (1 - cos(2*pi*n / (N - 1)))
- Ekstraksi 30 Fitur      :
    1. Band Energy Ratio (BER 600 - 1800 Hz) : mean & std (2 fitur)
    2. 13 MFCCs (Mel Filterbank + DCT-II)    : mean (13) & std (13) (26 fitur)
    3. Spectral Centroid & Pitch Modulation  : centroid_mean & f_peak_std (2 fitur)
- Algoritma Klasifikasi   : RandomForestClassifier(n_estimators=100, max_depth=10) + StandardScaler
- Output Model            : ml_engine/models/siren_rf_model.pkl
"""

import json
import os
import time
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
from scipy.fft import dct
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# Konstanta Pemrosesan Sinyal sesuai dokumen spesifikasi
SAMPLE_RATE = 16000
DURATION_SEC = 1.0
N_SAMPLES = int(SAMPLE_RATE * DURATION_SEC)
N_FFT = 1024
HOP_LENGTH = 512
N_MELS = 26
N_MFCC = 13
SIREN_BAND_LOW = 600.0
SIREN_BAND_HIGH = 1800.0
EPS = 1e-10

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
MODEL_PATH = MODELS_DIR / "siren_rf_model.pkl"
METRICS_PATH = MODELS_DIR / "training_metrics.json"


def hz_to_mel(hz: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def mel_to_hz(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def build_mel_filterbank(
    fs: int = SAMPLE_RATE, n_fft: int = N_FFT, n_mels: int = N_MELS
) -> np.ndarray:
    """Membangun matriks filterbank skala Mel untuk perhitungan MFCC."""
    f_min = 0.0
    f_max = fs / 2.0
    mel_points = np.linspace(hz_to_mel(np.array(f_min)), hz_to_mel(np.array(f_max)), n_mels + 2)
    hz_points = mel_to_hz(mel_points)
    bin_points = np.floor((n_fft + 1) * hz_points / fs).astype(int)

    n_bins = n_fft // 2 + 1
    filterbank = np.zeros((n_mels, n_bins), dtype=np.float64)

    for m in range(1, n_mels + 1):
        f_left = bin_points[m - 1]
        f_center = bin_points[m]
        f_right = bin_points[m + 1]

        for k in range(f_left, f_center):
            if f_center != f_left and 0 <= k < n_bins:
                filterbank[m - 1, k] = (k - f_left) / (f_center - f_left)
        for k in range(f_center, f_right):
            if f_right != f_center and 0 <= k < n_bins:
                filterbank[m - 1, k] = (f_right - k) / (f_right - f_center)

    return filterbank


_MEL_FILTERBANK = build_mel_filterbank()
_HANN_WINDOW = 0.5 * (1.0 - np.cos(2.0 * np.pi * np.arange(N_FFT) / (N_FFT - 1)))
_FFT_FREQS = np.fft.rfftfreq(N_FFT, d=1.0 / SAMPLE_RATE)
_SIREN_BAND_MASK = (_FFT_FREQS >= SIREN_BAND_LOW) & (_FFT_FREQS <= SIREN_BAND_HIGH)
_PITCH_SEARCH_MASK = (_FFT_FREQS >= 300.0) & (_FFT_FREQS <= 2500.0)


def get_feature_names() -> List[str]:
    names = ["ber_600_1800_mean", "ber_600_1800_std"]
    names += [f"mfcc_{i+1}_mean" for i in range(N_MFCC)]
    names += [f"mfcc_{i+1}_std" for i in range(N_MFCC)]
    names += ["spectral_centroid_mean", "pitch_modulation_std"]
    return names


def compute_stft_frames(signal: np.ndarray, fs: int = SAMPLE_RATE) -> Tuple[np.ndarray, np.ndarray]:
    """
    Menghitung Short-Time Fourier Transform (STFT) menggunakan jendela Hann:
    w[n] = 0.5 * (1 - cos(2*pi*n / (N - 1)))
    X(m, k) = sum_{n=0}^{N-1} x[n + mH] w[n] exp(-j 2*pi*k*n / N)
    """
    x = np.asarray(signal, dtype=np.float64).flatten()
    if len(x) < N_SAMPLES:
        x = np.pad(x, (0, N_SAMPLES - len(x)), mode="constant")
    elif len(x) > N_SAMPLES:
        x = x[:N_SAMPLES]

    # Hilangkan DC offset & normalisasi amplitudo puncak jika cukup kuat
    x = x - np.mean(x)
    peak = np.max(np.abs(x))
    if peak > 1e-4:
        x = x / peak

    n_frames = 1 + (len(x) - N_FFT) // HOP_LENGTH
    frames = np.lib.stride_tricks.as_strided(
        x,
        shape=(n_frames, N_FFT),
        strides=(x.strides[0] * HOP_LENGTH, x.strides[0]),
        writeable=False,
    )
    windowed = frames * _HANN_WINDOW
    stft_complex = np.fft.rfft(windowed, n=N_FFT, axis=1)
    mag_spectrum = np.abs(stft_complex)
    return _FFT_FREQS, mag_spectrum


def extract_stft_mfcc_features(
    signal: np.ndarray, fs: int = SAMPLE_RATE
) -> Tuple[np.ndarray, Dict[str, float]]:
    """
    Mengekstrak vektor fitur 30-dimensi dari sinyal audio 1 detik:
    - 2 fitur Band Energy Ratio (BER 600-1800 Hz: mean & std)
    - 26 fitur MFCC (13 mean + 13 std)
    - 2 fitur Spectral Centroid & Pitch Modulation Variance (f_peak std)
    """
    freqs, mag = compute_stft_frames(signal, fs=fs)
    power = mag ** 2

    # 1. Band Energy Ratio (BER) pada pita sirene 600 Hz - 1800 Hz
    band_energy = np.sum(power[:, _SIREN_BAND_MASK], axis=1)
    total_energy = np.sum(power, axis=1) + EPS
    ber_per_frame = band_energy / total_energy
    ber_mean = float(np.mean(ber_per_frame))
    ber_std = float(np.std(ber_per_frame))

    # 2. 13 MFCCs (rata-rata mu & standar deviasi sigma sepanjang jendela 1 detik = 26 fitur)
    mel_energy = np.dot(power, _MEL_FILTERBANK.T)
    log_mel_energy = np.log(mel_energy + EPS)
    mfcc_frames = dct(log_mel_energy, type=2, axis=1, norm="ortho")[:, :N_MFCC]
    mfcc_mean = np.mean(mfcc_frames, axis=0)
    mfcc_std = np.std(mfcc_frames, axis=0)

    # 3. Spectral Centroid & Pitch Modulation (variansi/std frekuensi puncak antar-frame)
    mag_sum = np.sum(mag, axis=1) + EPS
    centroids = np.sum(mag * freqs[None, :], axis=1) / mag_sum
    spectral_centroid_mean = float(np.mean(centroids))

    pitch_freqs = freqs[_PITCH_SEARCH_MASK]
    pitch_power = power[:, _PITCH_SEARCH_MASK]
    peak_indices = np.argmax(pitch_power, axis=1)
    peak_freqs = pitch_freqs[peak_indices]
    pitch_mod_std = float(np.std(peak_freqs))

    feature_vector = np.concatenate(
        [
            np.array([ber_mean, ber_std], dtype=np.float64),
            mfcc_mean.astype(np.float64),
            mfcc_std.astype(np.float64),
            np.array([spectral_centroid_mean, pitch_mod_std], dtype=np.float64),
        ]
    )

    summary = {
        "ber_mean": ber_mean,
        "ber_std": ber_std,
        "spectral_centroid_hz": spectral_centroid_mean,
        "pitch_mod_std_hz": pitch_mod_std,
        "peak_freq_mean_hz": float(np.mean(peak_freqs)),
    }
    return feature_vector, summary


# ==============================================================================
# GENERATOR DATASET AUDIO (SINTETIS REALISTIS + LOADER WAV LOKAL)
# ==============================================================================

def _generate_siren_sample(rng: np.random.Generator, noisy: bool = False) -> np.ndarray:
    """
    Menghasilkan sinyal sirene darurat (Wail, Yelp, atau Hi-Lo)
    dengan modulasi frekuensi (FM sweep 650-1600 Hz), harmonisa, dan AWGN/bising jalan.
    """
    t = np.linspace(0.0, DURATION_SEC, N_SAMPLES, endpoint=False)
    siren_type = rng.choice(["wail", "yelp", "hilo"], p=[0.45, 0.35, 0.20])

    f_low = rng.uniform(620.0, 820.0)
    f_high = rng.uniform(1300.0, 1680.0)
    phase0 = rng.uniform(0.0, 2.0 * np.pi)

    if siren_type == "wail":
        # Ayunan frekuensi naik-turun kontinu (ambulans)
        mod_rate = rng.uniform(0.9, 2.0)
        inst_freq = 0.5 * (f_high + f_low) + 0.5 * (f_high - f_low) * np.sin(
            2.0 * np.pi * mod_rate * t + phase0
        )
    elif siren_type == "yelp":
        # Ayunan cepat (pemadam kebakaran / patwal)
        mod_rate = rng.uniform(3.2, 6.0)
        saw = 2.0 * np.abs(2.0 * (t * mod_rate - np.floor(t * mod_rate + 0.5))) - 1.0
        inst_freq = 0.5 * (f_high + f_low) + 0.5 * (f_high - f_low) * saw
    else:
        # Hi-Lo dua nada bergantian (680 Hz <-> 1150 Hz)
        mod_rate = rng.uniform(1.8, 3.2)
        square = np.where(np.sin(2.0 * np.pi * mod_rate * t + phase0) >= 0.0, 1.0, -1.0)
        inst_freq = 0.5 * (f_high + f_low) + 0.38 * (f_high - f_low) * square

    # Integrasi frekuensi instan menjadi fase
    inst_phase = 2.0 * np.pi * np.cumsum(inst_freq) / SAMPLE_RATE
    signal = (
        0.75 * np.sin(inst_phase)
        + 0.18 * np.sin(2.0 * inst_phase + 0.3)
        + 0.07 * np.sin(3.0 * inst_phase + 0.7)
    )

    # Amplop jarak / efek akustik
    env = 1.0 - rng.uniform(0.05, 0.25) * np.cos(2.0 * np.pi * rng.uniform(0.5, 1.5) * t)
    signal = signal * env

    # Tambahkan noise sesuai skenario (Tenang vs Bising Jalan Raya)
    if noisy:
        # Simulasi jarak jauh (3m) + kebisingan jalan raya ekstrem & interferensi klakson
        atten = rng.uniform(0.25, 0.70)
        noise_std = rng.uniform(0.35, 0.95)
        engine_rumble = rng.uniform(0.20, 0.55) * np.sin(
            2.0 * np.pi * rng.uniform(70.0, 220.0) * t
        )
        # Interferensi nada statis di pita menengah pada sebagian sampel bising
        interf = (
            rng.uniform(0.0, 0.45)
            * np.sin(2.0 * np.pi * rng.uniform(650.0, 1500.0) * t)
            if rng.random() < 0.35
            else 0.0
        )
        signal = atten * signal + engine_rumble + interf + rng.normal(0.0, noise_std, size=N_SAMPLES)
    else:
        noise_std = rng.uniform(0.03, 0.18)
        signal = signal + rng.normal(0.0, noise_std, size=N_SAMPLES)

    return signal


def _generate_non_siren_sample(rng: np.random.Generator, noisy: bool = False) -> np.ndarray:
    """
    Menghasilkan sinyal Non-Sirene:
    1. Car Horn (klakson statis, termasuk yang berada di pita 600-1200 Hz tanpa modulasi FM)
    2. Engine Idling / Knalpot Motor
    3. Speech / Chatter Formant
    4. Street Ambience / Noise Latar
    """
    t = np.linspace(0.0, DURATION_SEC, N_SAMPLES, endpoint=False)
    category = rng.choice(["car_horn", "engine_exhaust", "speech_chatter", "street_noise"])

    if category == "car_horn":
        # Klakson memiliki frekuensi fundamental konstan (tidak berayun naik-turun)
        f1 = rng.uniform(380.0, 950.0)
        f2 = f1 * rng.uniform(1.18, 1.26)
        signal = 0.6 * np.sin(2.0 * np.pi * f1 * t) + 0.4 * np.sin(2.0 * np.pi * f2 * t)
        # Terkadang klakson ditekan putus-putus (on-off), tapi frekuensinya tetap statis
        if rng.random() < 0.5:
            gate = np.where(np.sin(2.0 * np.pi * rng.uniform(2.0, 4.0) * t) > -0.2, 1.0, 0.05)
            signal = signal * gate
    elif category == "engine_exhaust":
        f_base = rng.uniform(55.0, 210.0)
        jitter = rng.normal(0.0, 1.5, size=N_SAMPLES)
        phase = 2.0 * np.pi * np.cumsum(f_base + jitter) / SAMPLE_RATE
        signal = (
            0.65 * np.sin(phase)
            + 0.25 * np.sin(2.0 * phase)
            + 0.10 * np.sin(3.0 * phase)
        )
    elif category == "speech_chatter":
        # Simulasi formant percakapan dengan silabel acak
        f_formant1 = rng.uniform(180.0, 320.0)
        f_formant2 = rng.uniform(1800.0, 2800.0)
        syllable_env = np.abs(np.sin(2.0 * np.pi * rng.uniform(3.0, 6.0) * t)) ** 2
        signal = syllable_env * (
            0.5 * np.sin(2.0 * np.pi * f_formant1 * t)
            + 0.3 * np.sin(2.0 * np.pi * f_formant2 * t)
        )
    else:
        # Kebisingan angin / jalan raya (pink-like + white noise)
        white = rng.normal(0.0, 1.0, size=N_SAMPLES)
        kernel = np.ones(9) / 9.0
        signal = np.convolve(white, kernel, mode="same")

    noise_level = rng.uniform(0.20, 0.50) if noisy else rng.uniform(0.03, 0.15)
    signal = signal + rng.normal(0.0, noise_level, size=N_SAMPLES)
    return signal


def load_local_wav_dataset(dataset_dir: Path) -> Tuple[List[np.ndarray], List[int]]:
    """Memuat file .wav asli jika pengguna menaruhnya di dataset/siren dan dataset/non_siren."""
    signals: List[np.ndarray] = []
    labels: List[int] = []

    for label, subdir in [(1, "siren"), (0, "non_siren")]:
        folder = dataset_dir / subdir
        if not folder.exists():
            continue
        for wav_file in sorted(folder.glob("*.wav")):
            try:
                with wave.open(str(wav_file), "rb") as wf:
                    n_channels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    framerate = wf.getframerate()
                    raw = wf.readframes(wf.getnframes())
                    if sampwidth == 2:
                        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
                    else:
                        continue
                    if n_channels > 1:
                        audio = audio[::n_channels]
                    if framerate != SAMPLE_RATE and len(audio) > 0:
                        duration = len(audio) / framerate
                        target_len = int(duration * SAMPLE_RATE)
                        audio = np.interp(
                            np.linspace(0, len(audio) - 1, target_len),
                            np.arange(len(audio)),
                            audio,
                        )
                    # Potong per 1 detik
                    for start in range(0, max(1, len(audio) - N_SAMPLES + 1), N_SAMPLES):
                        chunk = audio[start : start + N_SAMPLES]
                        if len(chunk) >= N_SAMPLES // 2:
                            signals.append(chunk)
                            labels.append(label)
            except Exception:
                continue

    return signals, labels


def build_training_dataset(
    n_samples_per_class: int = 600, random_state: int = 42
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Membangun matriks fitur X (N, 30), vektor label y (N,), dan flag kondisi is_noisy (N,).
    """
    rng = np.random.default_rng(random_state)
    X_list: List[np.ndarray] = []
    y_list: List[int] = []
    noisy_flags: List[int] = []

    # Cek apakah ada dataset WAV lokal
    local_signals, local_labels = load_local_wav_dataset(BASE_DIR / "dataset")
    for sig, lbl in zip(local_signals, local_labels):
        feat, _ = extract_stft_mfcc_features(sig)
        X_list.append(feat)
        y_list.append(lbl)
        noisy_flags.append(0)

    # Bangkitkan sampel sintetis terkalibrasi (separuh kondisi tenang, separuh kondisi bising)
    for i in range(n_samples_per_class):
        is_noisy = i >= (n_samples_per_class // 2)

        sig_siren = _generate_siren_sample(rng, noisy=is_noisy)
        feat_siren, _ = extract_stft_mfcc_features(sig_siren)
        X_list.append(feat_siren)
        y_list.append(1)
        noisy_flags.append(int(is_noisy))

        sig_noise = _generate_non_siren_sample(rng, noisy=is_noisy)
        feat_noise, _ = extract_stft_mfcc_features(sig_noise)
        X_list.append(feat_noise)
        y_list.append(0)
        noisy_flags.append(int(is_noisy))

    X = np.vstack(X_list)
    y = np.array(y_list, dtype=np.int64)
    is_noisy_arr = np.array(noisy_flags, dtype=np.int64)
    return X, y, is_noisy_arr


def train_and_export_model() -> Dict:
    """
    Melatih Random Forest Classifier (n_estimators=100, max_depth=10) dengan StandardScaler,
    mengevaluasi metrik pada kondisi tenang & bising, dan mengekspor siren_rf_model.pkl.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 72)
    print("[AUDIO ML] Memulai Pembuatan Dataset & Ekstraksi 30 Fitur (STFT + MFCC)")
    print("=" * 72)

    t0 = time.perf_counter()
    X, y, is_noisy = build_training_dataset(n_samples_per_class=600, random_state=42)
    dataset_time = time.perf_counter() - t0
    print(f"[INFO] Dimensi Matriks Fitur X : {X.shape} (Target: N x 30 fitur)")
    print(f"[INFO] Distribusi Kelas        : Siren={int(np.sum(y == 1))}, Non-Siren={int(np.sum(y == 0))}")
    print(f"[INFO] Waktu Ekstraksi Fitur   : {dataset_time:.2f} detik")

    # Pembagian data 80% Training, 20% Testing (Stratified Split)
    stratify_key = y * 2 + is_noisy
    (
        X_train,
        X_test,
        y_train,
        y_test,
        noisy_train,
        noisy_test,
    ) = train_test_split(
        X, y, is_noisy, test_size=0.20, random_state=42, stratify=stratify_key
    )

    # Normalisasi fitur menggunakan StandardScaler
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Pelatihan Random Forest Classifier sesuai spesifikasi dokumen
    # n_jobs=1 memastikan latensi inferensi single-sample real-time < 5 ms tanpa overhead threadpool
    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        random_state=42,
        n_jobs=1,
    )
    clf.fit(X_train_scaled, y_train)

    # Pengukuran latensi inferensi per sampel
    t_inf_start = time.perf_counter()
    for i in range(min(50, len(X_test_scaled))):
        _ = clf.predict_proba(X_test_scaled[i : i + 1])
    avg_inference_ms = ((time.perf_counter() - t_inf_start) / min(50, len(X_test_scaled))) * 1000.0

    # Evaluasi Keseluruhan, Kondisi Tenang, dan Kondisi Bising
    y_pred = clf.predict(X_test_scaled)
    cm = confusion_matrix(y_test, y_pred)

    clean_mask = noisy_test == 0
    noisy_mask = noisy_test == 1

    def _calc_metrics(y_true_sub: np.ndarray, y_pred_sub: np.ndarray) -> Dict[str, float]:
        return {
            "accuracy": round(float(accuracy_score(y_true_sub, y_pred_sub)), 4),
            "precision": round(float(precision_score(y_true_sub, y_pred_sub, zero_division=0)), 4),
            "recall": round(float(recall_score(y_true_sub, y_pred_sub, zero_division=0)), 4),
            "f1_score": round(float(f1_score(y_true_sub, y_pred_sub, zero_division=0)), 4),
        }

    overall_metrics = _calc_metrics(y_test, y_pred)
    clean_metrics = _calc_metrics(y_test[clean_mask], y_pred[clean_mask])
    noisy_metrics = _calc_metrics(y_test[noisy_mask], y_pred[noisy_mask])

    feature_names = get_feature_names()
    importances = sorted(
        zip(feature_names, clf.feature_importances_), key=lambda x: x[1], reverse=True
    )

    metrics_report = {
        "model_type": "RandomForestClassifier",
        "hyperparameters": {"n_estimators": 100, "max_depth": 10, "random_state": 42},
        "signal_config": {
            "sample_rate_hz": SAMPLE_RATE,
            "duration_sec": DURATION_SEC,
            "n_fft": N_FFT,
            "hop_length": HOP_LENGTH,
            "window": "hann",
            "n_features": int(X.shape[1]),
            "siren_band_hz": [SIREN_BAND_LOW, SIREN_BAND_HIGH],
        },
        "dataset_summary": {
            "total_samples": int(len(y)),
            "train_samples": int(len(y_train)),
            "test_samples": int(len(y_test)),
        },
        "overall_metrics": overall_metrics,
        "clean_condition_metrics": clean_metrics,
        "noisy_condition_metrics": noisy_metrics,
        "confusion_matrix": cm.tolist(),
        "avg_inference_latency_ms": round(avg_inference_ms, 3),
        "top_5_features": [
            {"feature": name, "importance": round(float(imp), 4)}
            for name, imp in importances[:5]
        ],
    }

    # Simpan bundle model & scaler ke siren_rf_model.pkl
    model_bundle = {
        "model": clf,
        "scaler": scaler,
        "feature_names": feature_names,
        "config": metrics_report["signal_config"],
        "metrics": metrics_report,
        "threshold_emergency": 0.80,
    }
    joblib.dump(model_bundle, MODEL_PATH)

    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics_report, f, indent=2)

    print("\n[HASIL EVALUASI MODEL AUDIO SIRENE (TEST SET 20%)]")
    print(f"  - Akurasi Keseluruhan : {overall_metrics['accuracy']*100:.2f}%")
    print(f"  - Precision           : {overall_metrics['precision']:.4f}")
    print(f"  - Recall              : {overall_metrics['recall']:.4f}")
    print(f"  - F1-Score            : {overall_metrics['f1_score']:.4f} (Target >= 0.90)")
    print(f"  - Kondisi Tenang (F1) : {clean_metrics['f1_score']:.4f} (Prec={clean_metrics['precision']:.4f}, Rec={clean_metrics['recall']:.4f})")
    print(f"  - Kondisi Bising (F1) : {noisy_metrics['f1_score']:.4f} (Prec={noisy_metrics['precision']:.4f}, Rec={noisy_metrics['recall']:.4f})")
    print(f"  - Confusion Matrix    : TN={cm[0,0]}, FP={cm[0,1]}, FN={cm[1,0]}, TP={cm[1,1]}")
    print(f"  - Latensi Inferensi   : {avg_inference_ms:.3f} ms / sampel (Target < 5 ms)")
    print(f"\n[SAVED] Model diekspor ke : {MODEL_PATH}")
    print(f"[SAVED] Laporan metrik ke : {METRICS_PATH}")
    print("=" * 72)

    return metrics_report


if __name__ == "__main__":
    train_and_export_model()
