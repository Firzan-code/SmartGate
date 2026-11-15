"""Compile/run the actual SG90 sketch through fake HAL and loopback, without devices."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / 'smart_gate_full/firmware/demo_servo_esp32s3'
TESTS = ROOT / 'smart_gate_full/tests'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'reports/servo_firmware')
    args = parser.parse_args(argv)
    uv = shutil.which('uv')
    if not uv:
        parser.error('uv diperlukan untuk compiler Zig 0.14.1; lihat docs/PENGUJIAN.md')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    records = []
    sources = [SKETCH / 'demo_servo_esp32s3.ino', TESTS / 'servo_fw_sketch_test.cpp',
               TESTS / 'servo_fw_bridge.cpp', TESTS / 'servo_contract.py', Path(__file__).resolve()]
    sources += sorted((TESTS / 'servo_fw_stub').glob('*.h'))
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}

    def run(label, command):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=180)
        log = out / (label + '.log')
        log.write_bytes(('COMMAND ' + subprocess.list2cmdline(command) + '\nEXIT ' + str(result.returncode) +
                         '\n' + result.stdout + result.stderr).encode())
        records.append({'label': label, 'exit_code': result.returncode,
                        'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
                        'pass_lines': [line for line in result.stdout.splitlines() if line.startswith('PASS ')]})
        print(label, result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError(label + '\n' + result.stdout + result.stderr)
        return result.stdout

    compiler = [uv, 'run', '--no-project', '--python', sys.executable, '--with', 'ziglang==0.14.1',
                'python', '-m', 'ziglang', 'c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-DCONFIG_IDF_TARGET_ESP32S3=1', '-I', str(TESTS / 'servo_fw_stub'), '-I', str(SKETCH)]
    dummy = ['-DWIFI_SSID="TEST_ONLY_NOT_A_NETWORK"', '-DWIFI_PASSWORD=""', '-DSERVER_IP="192.0.2.20"']
    try:
        configured, empty, bridge = (out / name for name in ('servo_host.exe', 'servo_empty.exe', 'servo_bridge.exe'))
        run('host_compile', compiler + dummy + [str(TESTS / 'servo_fw_sketch_test.cpp'), '-o', str(configured)])
        names = run('host_list', [str(configured), '--list']).splitlines()
        if not names or len(names) != len(set(names)):
            raise RuntimeError('Empty/duplicate test discovery')
        for name in names:
            if name != 'empty_config_inert':
                run(name, [str(configured), name])
        run('empty_compile', compiler + [str(TESTS / 'servo_fw_sketch_test.cpp'), '-o', str(empty)])
        run('empty_config_inert', [str(empty), 'empty_config_inert'])
        wire_hex = (out / 'protocol_bytes.log').read_text().split('WIRE ')[1].splitlines()[0]
        if struct.unpack('<4sIII', bytes.fromhex(wire_hex)) != (b'SGH1', 0x12345678, 0x90abcdef, 1):
            raise RuntimeError('Production byte contract mismatch')
        run('bridge_compile', compiler + dummy + [str(TESTS / 'servo_fw_bridge.cpp'), '-o', str(bridge)])
        run('cpp_python_contract', [sys.executable, '-B', str(TESTS / 'servo_contract.py'), str(bridge), str(ROOT)])
    finally:
        after = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        manifest = {'runs': records, 'sources': hashes, 'sources_unchanged': hashes == after}
        (out / 'host_manifest.json').write_bytes(json.dumps(manifest, indent=2).encode())
    if hashes != after:
        raise RuntimeError('Source changed during tests')
    count = sum(len(r['pass_lines']) for r in records)
    print(f'PASS {count} kasus HAL/protokol/kontrak, tanpa ESP/webcam/COM.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
