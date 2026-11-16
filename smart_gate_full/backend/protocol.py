"""Versioned raw-ADC datagrams, independent of device and model libraries."""
from dataclasses import dataclass
import struct
import numpy as np

HEADER = struct.Struct('<4sIIIHH')
SAMPLE_RATE = 16000
SAMPLES_PER_PACKET = 320
FLAG_DISCONTINUITY = 1 << 0
FLAG_SERVO_PRESENT = 1 << 1
FLAG_SERVO_STATE_SHIFT = 2
FLAG_SERVO_STATE_MASK = 0b111 << FLAG_SERVO_STATE_SHIFT
KNOWN_FLAGS = FLAG_DISCONTINUITY | FLAG_SERVO_PRESENT | FLAG_SERVO_STATE_MASK
SERVO_STATES = {
    0: 'disabled',
    1: 'closed',
    2: 'open',
    3: 'cooldown',
    4: 'error',
}


@dataclass(frozen=True)
class AudioPacket:
    boot_id: int
    sequence: int
    sample_rate: int
    samples: np.ndarray
    discontinuity: bool
    servo_present: bool = False
    servo_state: str = 'unavailable'


def decode_audio_packet(data: bytes) -> AudioPacket:
    if len(data) != HEADER.size + SAMPLES_PER_PACKET * 2:
        raise ValueError('Ukuran paket audio tidak sesuai kontrak')
    magic, boot, sequence, rate, count, flags = HEADER.unpack_from(data)
    servo_present = bool(flags & FLAG_SERVO_PRESENT)
    servo_code = (flags & FLAG_SERVO_STATE_MASK) >> FLAG_SERVO_STATE_SHIFT
    if (magic != b'SGA1' or rate != SAMPLE_RATE or count != SAMPLES_PER_PACKET
            or flags & ~KNOWN_FLAGS or servo_code not in SERVO_STATES
            or (not servo_present and servo_code != 0)):
        raise ValueError('Header audio tidak valid')
    samples = np.frombuffer(data, dtype='<u2', offset=HEADER.size).copy()
    if np.any(samples > 4095):
        raise ValueError('Sampel ADC di luar resolusi 12 bit')
    return AudioPacket(boot, sequence, rate, samples,
                       bool(flags & FLAG_DISCONTINUITY), servo_present,
                       SERVO_STATES[servo_code] if servo_present else 'unavailable')
