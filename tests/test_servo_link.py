"""Dedicated servo protocol over real loopback; no physical ESP."""
from pathlib import Path
import socket
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
WIRE = struct.Struct('<4sIII')


class ServoLinkTests(unittest.TestCase):
    def test_arm_and_one_open_with_ack_on_loopback(self):
        self.assertTrue((ROOT / 'smart_gate_full/backend/servo_link.py').is_file(), 'Missing servo link')
        from smart_gate_full.backend.servo_link import ServoLink
        esp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        esp.bind(('127.0.0.1', 0))
        esp.settimeout(1)
        link = ServoLink('127.0.0.1', local_port=0, esp_port=esp.getsockname()[1])
        try:
            esp.sendto(WIRE.pack(b'SGH1', 123, 77, 0), link.address)
            link.poll(0.)
            self.assertTrue(link.arm(0.))
            raw, addr = esp.recvfrom(100)
            self.assertEqual(WIRE.unpack(raw), (b'SGC1', 123, 77, 1))
            esp.sendto(WIRE.pack(b'SGK1', 123, 77, 1), addr)
            link.poll(.01)
            self.assertTrue(link.ready(.01))
            self.assertTrue(link.open_once(.02))
            self.assertEqual(WIRE.unpack(esp.recvfrom(100)[0]), (b'SGC1', 123, 77, 2))
            esp.sendto(WIRE.pack(b'SGK1', 123, 77, 2), addr)
            link.poll(.03)
            self.assertEqual(link.state, 2)
            self.assertFalse(link.open_once(.04))
        finally:
            link.close()
            esp.close()

    def test_wrong_source_oversize_and_reboot_do_not_arm(self):
        from smart_gate_full.backend.servo_link import ServoLink
        esp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        stranger = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        esp.bind(('127.0.0.1', 0))
        link = ServoLink('127.0.0.1', local_port=0, esp_port=esp.getsockname()[1])
        try:
            stranger.sendto(WIRE.pack(b'SGH1', 1, 1, 0), link.address)
            esp.sendto(WIRE.pack(b'SGH1', 1, 1, 0) + b'x' * 1000, link.address)
            link.poll(0.)
            self.assertFalse(link.arm(0.))
            esp.sendto(WIRE.pack(b'SGH1', 1, 2, 0), link.address)
            link.poll(.1)
            self.assertFalse(link.arm(1.))
            esp.sendto(WIRE.pack(b'SGH1', 2, 3, 0), link.address)
            link.poll(1.1)
            self.assertTrue(link.error)
            self.assertFalse(link.arm(1.1))
        finally:
            link.close()
            esp.close()
            stranger.close()

    def test_heartbeat_cannot_regress_confirmed_state(self):
        from smart_gate_full.backend.servo_link import ServoLink
        esp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        esp.bind(('127.0.0.1', 0))
        esp.settimeout(1)
        link = ServoLink('127.0.0.1', local_port=0, esp_port=esp.getsockname()[1])
        try:
            esp.sendto(WIRE.pack(b'SGH1', 9, 11, 0), link.address)
            link.poll(0.)
            link.arm(0.)
            esp.recvfrom(100)
            esp.sendto(WIRE.pack(b'SGK1', 9, 11, 1), link.address)
            link.poll(.01)
            link.open_once(.02)
            esp.recvfrom(100)
            esp.sendto(WIRE.pack(b'SGK1', 9, 11, 2), link.address)
            link.poll(.03)
            esp.sendto(WIRE.pack(b'SGH1', 9, 11, 1), link.address)
            link.poll(.04)
            self.assertEqual(link.state, 2)
            self.assertFalse(link.open_once(.05))
            link.poll(2.)
            self.assertTrue(link.error)
            self.assertFalse(link.fresh(2.))
        finally:
            link.close()
            esp.close()


    def test_obsolete_beacon_cannot_replace_nonce_or_freshness(self):
        from smart_gate_full.backend.servo_link import ServoLink
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as esp:
            esp.bind(('127.0.0.1', 0))
            link = ServoLink('127.0.0.1', local_port=0, esp_port=esp.getsockname()[1])
            try:
                esp.sendto(WIRE.pack(b'SGH1', 9, 11, 0), link.address)
                link.poll(0.)
                link.arm(0.)
                esp.sendto(WIRE.pack(b'SGK1', 9, 11, 1), link.address)
                link.poll(.01)
                esp.sendto(WIRE.pack(b'SGH1', 9, 22, 1), link.address)
                link.poll(.5)
                esp.sendto(WIRE.pack(b'SGH1', 9, 11, 0), link.address)
                link.poll(.6)
                self.assertEqual((link.nonce, link.nonce_at, link.received_at), (22, .5, .5))
            finally:
                link.close()


if __name__ == '__main__':
    unittest.main()
