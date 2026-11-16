"""Bounded, discontinuity-aware windows of raw ADC samples (single producer)."""
from collections import deque
from dataclasses import dataclass
import numpy as np

from .protocol import AudioPacket, SAMPLE_RATE


@dataclass(frozen=True)
class AudioWindow:
    samples: np.ndarray
    generation: int
    sequence: int
    received_at: float
    adc_min: int
    adc_max: int
    adc_avg: float


class AudioStream:
    def __init__(self, blocks_per_window=50, hop_blocks=25):
        if (not isinstance(blocks_per_window, int) or not isinstance(hop_blocks, int)
                or blocks_per_window < 1 or hop_blocks < 1 or hop_blocks > blocks_per_window):
            raise ValueError('Ukuran window/hop audio tidak valid')
        self.blocks_per_window = blocks_per_window
        self.hop_blocks = hop_blocks
        self._blocks = deque(maxlen=blocks_per_window)
        self._retired = deque(maxlen=8)
        self.peer = None
        self.boot = None
        self.expected = None
        self.last_packet = None
        self.generation = 0
        self.packets = self.gaps = self.rejected = 0
        self._until_hop = 0
        self.servo_present = False
        self.servo_state = 'unavailable'

    def _reset(self):
        self.generation += 1
        self._blocks.clear()
        self._until_hop = 0

    def push(self, packet: AudioPacket, peer, now: float):
        idle = self.last_packet is not None and now - self.last_packet > .3
        if self.peer is not None and peer != self.peer and not idle:
            self.rejected += 1
            return None
        if (peer, packet.boot_id) in self._retired:
            self.rejected += 1
            return None
        if self.peer != peer or self.boot != packet.boot_id:
            if self.peer is not None:
                self._retired.append((self.peer, self.boot))
            self.peer, self.boot, self.expected = peer, packet.boot_id, None
            self._reset()
        if self.expected is not None:
            distance = (packet.sequence - self.expected) & 0xffffffff
            if distance >= 0x80000000:
                self.rejected += 1  # duplicate/late packet must not enter a window
                return None
            if distance or packet.discontinuity or idle:
                self.gaps += 1
                self._reset()
        elif packet.discontinuity:
            self.gaps += 1
            self._reset()
        self.expected = (packet.sequence + 1) & 0xffffffff
        self.last_packet = now
        self.servo_present = packet.servo_present
        self.servo_state = packet.servo_state
        self.packets += 1
        self._blocks.append(packet.samples)
        self._until_hop += 1
        if len(self._blocks) < self.blocks_per_window or self._until_hop < self.hop_blocks:
            return None
        self._until_hop = 0
        raw = np.concatenate(self._blocks)
        return AudioWindow(raw, self.generation, packet.sequence, now,
                           int(raw.min()), int(raw.max()), float(raw.mean()))

    def snapshot(self, now):
        age = None if self.last_packet is None else max(0., now - self.last_packet)
        status = 'waiting' if age is None else 'stale' if age > .3 else 'live'
        return {'status': status, 'peer': None if self.peer is None else f'{self.peer[0]}:{self.peer[1]}',
                'packets': self.packets, 'gaps': self.gaps, 'rejected': self.rejected,
                'seconds_since_packet': None if age is None else round(age, 3),
                'sample_rate_hz': SAMPLE_RATE, 'udp_port': 5006,
                'buffer_samples': len(self._blocks) * 320, 'generation': self.generation}
