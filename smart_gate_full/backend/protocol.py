"""Versioned raw-ADC datagrams, independent of device and model libraries."""
from dataclasses import dataclass
import struct
import numpy as np

HEADER = struct.Struct('<4sIIIHH')
SAMPLE_RATE = 16000
SAMPLES_PER_PACKET = 320


@dataclass(frozen=True)
class AudioPacket:
    boot_id: int
    sequence: int
    sample_rate: int
    samples: np.ndarray
    discontinuity: bool


def decode_audio_packet(data: bytes) -> AudioPacket:
    if len(data) != HEADER.size + SAMPLES_PER_PACKET * 2:
        raise ValueError('Ukuran paket audio tidak sesuai kontrak')
    magic, boot, sequence, rate, count, flags = HEADER.unpack_from(data)
    if magic != b'SGA1' or rate != SAMPLE_RATE or count != SAMPLES_PER_PACKET or flags & ~1:
        raise ValueError('Header audio tidak valid')
    samples = np.frombuffer(data, dtype='<u2', offset=HEADER.size).copy()
    if np.any(samples > 4095):
        raise ValueError('Sampel ADC di luar resolusi 12 bit')
    return AudioPacket(boot, sequence, rate, samples, bool(flags & 1))
