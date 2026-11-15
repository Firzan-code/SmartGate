"""Bounded UDP control for an explicitly armed SG90 bench demo (trusted LAN only)."""
import ipaddress
import socket
import struct

WIRE = struct.Struct('<4sIII')
STATES = {0: 'IDLE / PWM NONAKTIF', 1: 'ARMED / TARGET 90', 2: 'OPENED / TARGET 110',
          3: 'ERROR PWM', 4: 'DISARMED / PWM DILEPAS'}


class ServoLink:
    def __init__(self, esp_ip, local_port=5010, esp_port=5009):
        self.peer = (str(ipaddress.IPv4Address(esp_ip)), esp_port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(('0.0.0.0', local_port))
            self.socket.setblocking(False)
        except Exception:
            self.socket.close()
            raise
        port = self.socket.getsockname()[1]
        self.address = ('127.0.0.1', port)
        self.boot = self.nonce = self.state = self.nonce_at = self.received_at = None
        self.arm_sent = self.open_sent = False
        self.last_keepalive = float('-inf')
        self.error = None

    def poll(self, now):
        for _ in range(64):
            try:
                raw, peer = self.socket.recvfrom(65535)
            except BlockingIOError:
                break
            except OSError as exc:
                self.error = f'UDP: {exc}'
                break
            if peer != self.peer or len(raw) != WIRE.size:
                continue
            magic, boot, nonce, state = WIRE.unpack(raw)
            if magic not in (b'SGH1', b'SGK1') or not boot or not nonce or state not in STATES:
                continue
            if self.boot is not None and boot != self.boot:
                self.error = 'ESP restart; hentikan dan mulai ulang demo secara eksplisit'
                continue
            if self.boot is None:
                if magic != b'SGH1':
                    continue
                self.boot = boot
                if state != 0:
                    self.error = 'ESP bukan IDLE; reboot manual untuk sesi baru'
            if magic == b'SGK1' and nonce != self.nonce:
                continue
            if self.state in (1, 2) and state < self.state:
                continue  # Reject obsolete packets before changing nonce/freshness.
            if nonce != self.nonce:
                self.nonce = nonce
                self.nonce_at = now
            self.received_at = now
            self.state = state
            if state in (3, 4):
                self.error = STATES[state]
        if self.received_at is not None and now - self.received_at > 1.5:
            self.error = 'Koneksi ESP basi; hentikan lalu mulai ulang sesi'

    def fresh(self, now):
        return (not self.error and self.boot is not None and self.nonce_at is not None
                and 0 <= now - self.nonce_at <= .70 and self.received_at is not None
                and 0 <= now - self.received_at <= .70)

    def _send(self, action, now):
        if not self.fresh(now):
            return False
        try:
            self.socket.sendto(WIRE.pack(b'SGC1', self.boot, self.nonce, action), self.peer)
            return True
        except OSError as exc:
            self.error = f'Kirim gagal: {exc}'
            return False

    def arm(self, now):
        if self.state != 0 or self.open_sent:
            return False
        sent = self._send(1, now)
        self.arm_sent = self.arm_sent or sent
        return sent

    def ready(self, now):
        return self.arm_sent and self.state == 1 and self.fresh(now)

    def open_once(self, now):
        if self.open_sent or not self.ready(now):
            return False
        self.open_sent = self._send(2, now)
        return self.open_sent

    def keepalive(self, now):
        if self.arm_sent and self.state in (1, 2) and now - self.last_keepalive >= .20:
            if self._send(4, now):
                self.last_keepalive = now

    def disarm(self, now):
        return self._send(3, now)

    def snapshot(self):
        return {'state': self.state, 'status': STATES.get(self.state, 'MENUNGGU BEACON ESP'),
                'arm_sent': self.arm_sent, 'open_sent': self.open_sent,
                'open_acknowledged': self.state == 2, 'error': self.error}

    def close(self):
        self.socket.close()
