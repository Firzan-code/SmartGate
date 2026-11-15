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
    def __init__(self):
        self._blocks = deque(maxlen=50)
        self._retired = deque(maxlen=8)
        self.peer = None
        self.boot = None
        self.expected = None
        self.last_packet = None
        self.generation = 0
        self.packets = self.gaps = self.rejected = 0
        self._until_hop = 0

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
        self.packets += 1
        self._blocks.append(packet.samples)
        self._until_hop += 1
        if len(self._blocks) < 50 or self._until_hop < 25:
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
