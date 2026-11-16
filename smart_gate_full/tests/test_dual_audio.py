"""AST buffering/debounce tests with explicit fake probabilities."""
import importlib
import unittest
import numpy as np


class AudioContractTests(unittest.TestCase):
    def test_ast_three_second_inference_debounce_and_gap_reset(self):
        try:
            module = importlib.import_module('smart_gate_full.backend.audio_model')
        except ModuleNotFoundError:
            self.fail('Missing direct waveform classifier without synthetic fallback')
        from smart_gate_full.backend.stream import AudioWindow
        class FakeAST:
            def predict(self, audio):
                self.last_audio = audio
                return {'class_name': 'ambulance', 'probability': .85,
                        'all_probabilities': {'ambulance': .85, 'other_siren': .05,
                                              'traffic_noise': .10}}
        ast = FakeAST()
        adc = np.arange(48000, dtype=np.uint16) % 1800 + 1000
        classifier = module.AudioClassifier(ast_model=ast)
        def window(generation, seq):
            return AudioWindow(adc, generation, seq, 0., int(adc.min()), int(adc.max()), float(adc.mean()))
        first = classifier.predict(window(1, 149))
        self.assertEqual(first['source'], 'MAX9814_ESP32')
        self.assertEqual(first['model_name'], 'siren_ast_v2')
        self.assertEqual(first['siren_probability'], .9)
        self.assertFalse(first['siren_detected'])
        self.assertEqual(ast.last_audio.shape, (48000,))
        second = classifier.predict(window(1, 299))
        self.assertTrue(second['siren_detected'])
        reset = classifier.predict(window(2, 449))
        self.assertFalse(reset['siren_detected'])
        self.assertEqual(reset['consecutive_hits'], 1)
        self.assertGreater(len(second['spectrum_freqs_hz']), 10)
        with self.assertRaises(FileNotFoundError):
            module.AudioClassifier(model_path='nonexistent-local-model.onnx')


if __name__ == '__main__':
    unittest.main()
