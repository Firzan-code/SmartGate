"""Fixtures explicitly represent transport tests, not microphone readings."""
import importlib
import struct
import unittest


class PacketContractTests(unittest.TestCase):
    def test_decode_raw_adc_packet(self):
        try:
            module = importlib.import_module('smart_gate_full.backend.protocol')
        except ModuleNotFoundError:
            self.fail('Missing UDP audio packet parser')
        raw = struct.pack('<4sIIIHH', b'SGA1', 7, 42, 16000, 320, 0)
        raw += struct.pack('<320H', *range(320))
        packet = module.decode_audio_packet(raw)
        self.assertEqual((packet.boot_id, packet.sequence, packet.sample_rate), (7, 42, 16000))
        self.assertEqual(len(packet.samples), 320)
        self.assertEqual(int(packet.samples[-1]), 319)
        self.assertFalse(packet.discontinuity)

    def test_invalid_payloads_are_rejected(self):
        from smart_gate_full.backend.protocol import decode_audio_packet
        good = struct.pack('<4sIIIHH', b'SGA1', 7, 42, 16000, 320, 0) + struct.pack('<320H', *range(320))
        cases = [good[:-1], good + b'0', b'BAD!' + good[4:],
                 good[:12] + struct.pack('<I', 4000) + good[16:],
                 good[:18] + struct.pack('<H', 2) + good[20:],
                 good[:20] + struct.pack('<H', 4096) + good[22:]]
        for raw in cases:
            with self.subTest(raw=raw[:20]):
                with self.assertRaises(ValueError):
                    decode_audio_packet(raw)


class ContinuityTests(unittest.TestCase):
    def test_full_window_requires_50_contiguous_packets(self):
        import numpy as np
        try:
            module = importlib.import_module('smart_gate_full.backend.stream')
        except ModuleNotFoundError:
            self.fail('Missing bounded continuous audio window assembler')
        from smart_gate_full.backend.protocol import AudioPacket
        stream = module.AudioStream()
        for seq in range(49):
            packet = AudioPacket(1, seq, 16000, np.full(320, 1400, dtype=np.uint16), False)
            self.assertIsNone(stream.push(packet, ('192.0.2.1', 5007), seq * .02))
        window = stream.push(AudioPacket(1, 49, 16000, np.full(320, 1500, dtype=np.uint16), False), ('192.0.2.1', 5007), .98)
        self.assertEqual(window.samples.shape, (16000,))
        self.assertEqual(window.adc_min, 1400)
        self.assertEqual(window.adc_max, 1500)
        self.assertEqual(window.sequence, 49)
        self.assertEqual(stream.snapshot(.99)['status'], 'live')
        self.assertEqual(stream.snapshot(.99)['packets'], 50)
        self.assertEqual(stream.snapshot(4)['status'], 'stale')

    def test_gaps_overflow_reboot_and_sequence_wrap(self):
        import numpy as np
        from smart_gate_full.backend.protocol import AudioPacket
        from smart_gate_full.backend.stream import AudioStream
        peer = ('192.0.2.2', 5007)
        stream = AudioStream()
        def add(seq, t, flag=False, boot=1, address=peer):
            return stream.push(AudioPacket(boot, seq, 16000, np.full(320, 1450, np.uint16), flag), address, t)
        for seq in range(49):
            self.assertIsNone(add(seq, seq * .02))
        self.assertIsNone(add(50, .99))  # missing sequence 49 cannot complete a window
        self.assertEqual(stream.snapshot(.99)['buffer_samples'], 320)
        generation = stream.generation
        self.assertIsNone(add(50, 1.0))  # duplicate
        self.assertEqual(stream.snapshot(1.)['buffer_samples'], 320)
        self.assertIsNone(add(51, 1.01, flag=True))
        self.assertGreater(stream.generation, generation)
        self.assertEqual(stream.snapshot(1.01)['buffer_samples'], 320)
        self.assertIsNone(add(0, 1.02, boot=2))
        self.assertIsNone(add(52, 1.03, boot=1))  # delayed retired boot
        self.assertEqual(stream.boot, 2)
        self.assertIsNone(add(1, 1.04, boot=2, address=('192.0.2.3', 5007)))
        self.assertEqual(stream.peer, peer)
        self.assertGreaterEqual(stream.rejected, 3)
        other = AudioStream()
        other.push(AudioPacket(1, 0xffffffff, 16000, np.ones(320, np.uint16), False), peer, 0.)
        other.push(AudioPacket(1, 0, 16000, np.ones(320, np.uint16), False), peer, .02)
        self.assertEqual(other.gaps, 0)
        self.assertEqual(other.snapshot(.02)['buffer_samples'], 640)


if __name__ == '__main__':
    unittest.main()
