"""Trusted local AST ONNX inference with Hugging Face-compatible fbank input."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np


DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models" / "siren_ast_v2"


def resolve_model_dir(model_path=None) -> Path:
    configured = model_path or os.environ.get("SMARTGATE_AST_MODEL_DIR")
    path = Path(configured).expanduser() if configured else DEFAULT_MODEL_DIR
    if path.suffix.lower() == ".onnx":
        path = path.parent
    path = path.resolve()
    required = ("siren_ast_fp16.onnx", "labels.json", "preprocessor_config.json")
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Model AST tidak lengkap di {path}: {', '.join(missing)}")
    return path


class ASTSirenModel:
    """Load one ONNX session and reproduce ASTFeatureExtractor preprocessing."""

    def __init__(self, model_path=None):
        self.model_dir = resolve_model_dir(model_path)
        with (self.model_dir / "labels.json").open(encoding="utf-8") as handle:
            labels = json.load(handle)
        with (self.model_dir / "preprocessor_config.json").open(encoding="utf-8") as handle:
            config = json.load(handle)

        self.labels = [labels["id2label"][str(index)] for index in range(len(labels["id2label"]))]
        self.sample_rate = int(labels["target_sr"])
        self.clip_duration = float(labels["clip_duration"])
        self.max_length = int(config["max_length"])
        self.mel_bins = int(config["num_mel_bins"])
        self.mean = float(config["mean"])
        self.std = float(config["std"])
        if (self.sample_rate != 16000 or self.clip_duration != 3.0 or self.max_length != 1024
                or self.mel_bins != 128 or not math.isfinite(self.mean)
                or not math.isfinite(self.std) or self.std <= 0):
            raise ValueError("Konfigurasi preprocessor AST tidak sesuai kontrak SmartGate")

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("onnxruntime belum terpasang") from exc
        options = ort.SessionOptions()
        options.intra_op_num_threads = min(4, os.cpu_count() or 1)
        self.session = ort.InferenceSession(
            str(self.model_dir / "siren_ast_fp16.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        inputs, outputs = self.session.get_inputs(), self.session.get_outputs()
        if (len(inputs) != 1 or inputs[0].type != "tensor(float)"
                or list(inputs[0].shape[1:]) != [1024, 128]):
            raise ValueError("Input ONNX AST harus float [batch, 1024, 128]")
        if len(outputs) != 1 or outputs[0].type != "tensor(float)" or outputs[0].shape[-1] != len(self.labels):
            raise ValueError("Output ONNX AST tidak cocok dengan labels.json")
        self.input_name, self.output_name = inputs[0].name, outputs[0].name
        try:
            import torch
            from torchaudio.compliance import kaldi
        except ImportError as exc:
            raise RuntimeError("torch dan torchaudio belum terpasang") from exc
        self._torch, self._kaldi = torch, kaldi
        torch.set_num_threads(1)
        # Import and execution warm-up must finish before UDP starts. Otherwise
        # the first multi-second import can make fresh audio windows go stale.
        warm_input = self.preprocess(np.zeros(48000, dtype=np.float32))
        self.session.run([self.output_name], {self.input_name: warm_input})

    def preprocess(self, audio) -> np.ndarray:
        samples = np.asarray(audio, dtype=np.float32)
        expected = int(self.sample_rate * self.clip_duration)
        if samples.shape != (expected,) or not np.isfinite(samples).all():
            raise ValueError(f"AST memerlukan audio finite {expected} sampel")
        waveform = self._torch.from_numpy(samples).unsqueeze(0)
        waveform = waveform - waveform.mean()
        features = self._kaldi.fbank(
            waveform,
            htk_compat=True,
            sample_frequency=float(self.sample_rate),
            use_energy=False,
            window_type="hanning",
            num_mel_bins=self.mel_bins,
            dither=0.0,
            frame_shift=10,
        ).cpu().numpy().astype(np.float32, copy=False)
        if features.shape[0] < self.max_length:
            features = np.pad(features, ((0, self.max_length - features.shape[0]), (0, 0)))
        else:
            features = features[:self.max_length]
        # ASTFeatureExtractor normalizes after padding and uses std * 2.
        features = (features - self.mean) / (self.std * 2.0)
        return features[np.newaxis, ...].astype(np.float32, copy=False)

    def predict(self, audio) -> dict:
        inputs = self.preprocess(audio)
        logits = np.asarray(
            self.session.run([self.output_name], {self.input_name: inputs})[0],
            dtype=np.float64,
        ).reshape(-1)
        if logits.shape != (len(self.labels),) or not np.isfinite(logits).all():
            raise ValueError("Model AST mengembalikan logits invalid")
        shifted = logits - logits.max()
        probabilities = np.exp(shifted)
        probabilities /= probabilities.sum()
        if not np.isfinite(probabilities).all():
            raise ValueError("Softmax AST menghasilkan probabilitas invalid")
        index = int(np.argmax(probabilities))
        return {
            "class_id": index,
            "class_name": self.labels[index],
            "probability": float(probabilities[index]),
            "all_probabilities": {
                label: float(probabilities[i]) for i, label in enumerate(self.labels)
            },
        }
