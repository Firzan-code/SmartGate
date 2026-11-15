"""Real model artifact tests with explicit generated fixtures, NOT physical tests."""
import importlib
import unittest
import numpy as np


class AudioContractTests(unittest.TestCase):
    def test_real_model_inference_debounce_and_gap_reset(self):
        try:
            module = importlib.import_module('smart_gate_full.backend.audio_model')
        except ModuleNotFoundError:
            self.fail('Missing direct waveform classifier without synthetic fallback')
        from ml_engine.train_siren_model import _generate_siren_sample
        from smart_gate_full.backend.stream import AudioWindow
        signal = _generate_siren_sample(np.random.default_rng(91), noisy=False)
        adc = np.rint(1500 + signal / np.max(np.abs(signal)) * 900).astype(np.uint16)
        classifier = module.AudioClassifier()
        def window(generation, seq):
            return AudioWindow(adc, generation, seq, 0., int(adc.min()), int(adc.max()), float(adc.mean()))
        first = classifier.predict(window(1, 49))
        self.assertEqual(first['source'], 'MAX9814_ESP32')
        self.assertGreaterEqual(first['siren_probability'], .8)
        self.assertFalse(first['siren_detected'])
        second = classifier.predict(window(1, 74))
        self.assertTrue(second['siren_detected'])
        reset = classifier.predict(window(2, 124))
        self.assertFalse(reset['siren_detected'])
        self.assertEqual(reset['consecutive_hits'], 1)
        self.assertGreater(len(reset['spectrum_freqs_hz']), 10)
        with self.assertRaises(FileNotFoundError):
            module.AudioClassifier(model_path='nonexistent-local-model.pkl')


if __name__ == '__main__':
    unittest.main()
