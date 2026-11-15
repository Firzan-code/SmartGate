"""Batas pengamatan bilateral; tidak mengakses kamera atau wajah."""
import unittest

from ml_engine.eye_blink import BlinkStateMachine


class TestBilateralClosure(unittest.TestCase):
    def test_one_eye_reopening_cannot_extend_short_bilateral_closure(self):
        blink = BlinkStateMachine()
        blink.update(0.31, 0.31, 0.0)
        blink.update(0.14, 0.14, 0.10)
        blink.update(0.31, 0.14, 0.11)
        state = blink.update(0.31, 0.31, 0.30)
        self.assertEqual(state['total_blinks'], 0,
                         'Bukaan satu mata tidak boleh memperpanjang 10 ms menjadi kedipan sah')
        self.assertFalse(state['liveness_verified'])
        # Riwayat dibatalkan, tetapi buka penuh dapat memulai kedipan berikutnya.
        blink.update(0.14, 0.14, 0.40)
        state = blink.update(0.31, 0.31, 0.55)
        self.assertEqual(state['total_blinks'], 1)


if __name__ == '__main__':
    unittest.main()
