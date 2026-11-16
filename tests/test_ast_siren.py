"""Contract checks for the trusted local siren_ast_v2 artifact."""
import unittest

import numpy as np

from ml_engine.ast_siren import ASTSirenModel, DEFAULT_MODEL_DIR


@unittest.skipUnless((DEFAULT_MODEL_DIR / 'siren_ast_fp16.onnx').is_file(),
                     'Model AST lokal tidak tersedia')
class ASTSirenModelTests(unittest.TestCase):
    def test_real_model_returns_softmax_probabilities(self):
        model = ASTSirenModel()
        result = model.predict(np.zeros(48000, dtype=np.float32))
        self.assertIn(result['class_name'], {'ambulance', 'other_siren', 'traffic_noise'})
        self.assertAlmostEqual(sum(result['all_probabilities'].values()), 1.0, places=6)
        self.assertTrue(all(0 <= value <= 1 for value in result['all_probabilities'].values()))


if __name__ == '__main__':
    unittest.main()
