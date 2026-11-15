"""Production fake-HAL MCU <-> real Python UDP link, no physical devices."""
from pathlib import Path
import select
import socket
import subprocess
import sys


def exercise_bridge(executable, root):
    sys.path.insert(0, str(root))
    from smart_gate_full.backend.servo_link import ServoLink, WIRE
    from smart_gate_full.backend.servo_demo import ServoController
    process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, bufsize=1)
    esp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    esp.bind(('127.0.0.1', 0))
    link = ServoLink('127.0.0.1', local_port=0, esp_port=esp.getsockname()[1])
    writes = state = None
    actions = []

    def output():
        nonlocal writes, state
        while True:
            line = process.stdout.readline().strip()
            if not line:
                raise RuntimeError('Bridge terminated: ' + process.stderr.read())
            if line == 'END':
                break
            if line.startswith('WIRE '):
                esp.sendto(bytes.fromhex(line[5:]), link.address)
            elif line.startswith('STATE '):
                parts = line.split()
                state, writes = int(parts[1]), int(parts[3])

    def request(command):
        process.stdin.write(command + '\n')
        process.stdin.flush()
        output()

    def consume_commands(at):
        # A complete round trip is synchronous in this harness, not a fake ACK.
        while select.select([esp], [], [], .01)[0]:
            raw, _ = esp.recvfrom(65535)
            actions.append(WIRE.unpack(raw)[3])
            request('RX ' + str(round(at * 1000)) + ' ' + raw.hex())
            link.poll(at)

    try:
        output()
        link.poll(0.)
        assert link.state == 0 and writes == 0
        assert link.arm(0.)
        consume_commands(.01)
        assert link.ready(.01) and writes == 1 and state == 1
        controller = ServoController(link)
        controller.tick(.02)
        consume_commands(.02)
        opened = {'face_detected': True, 'left_eye_state': 'TERBUKA', 'right_eye_state': 'TERBUKA'}
        for index in range(1, 65):
            at = index / 10
            request('TICK ' + str(index * 100))
            controller.tick(at)
            consume_commands(at)
            controller.on_frame(opened, at, now=at)
            consume_commands(at)
            if index < 51:
                assert writes == 1 and state == 1, (index, writes, state)
        assert controller.gate.fired and link.state == 2 and writes == 2 and state == 2
        assert actions.count(2) == 1, actions
        assert link.snapshot()['open_acknowledged']
        print('PASS production_cpp_python_udp_5s_one_open', flush=True)
        assert link.disarm(6.4)
        consume_commands(6.4)
        assert state == 4 and writes == 2
        print('PASS production_cpp_python_disarm_without_close', flush=True)
    finally:
        link.close()
        esp.close()
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


if __name__ == '__main__':
    exercise_bridge(Path(sys.argv[1]), Path(sys.argv[2]))
