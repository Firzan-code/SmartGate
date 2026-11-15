"""Compile and run production firmware with fake HAL; never opens real devices."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / 'smart_gate_full/firmware/tes_dua_model_esp32s3'
TESTS = ROOT / 'smart_gate_full/tests'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'reports/firmware_host')
    args = parser.parse_args(argv)
    uv = shutil.which('uv')
    if not uv:
        parser.error('uv diperlukan untuk menjalankan compiler Zig; lihat docs/PENGUJIAN.md')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    compiler = [uv, 'run', '--no-project', '--python', sys.executable,
                '--with', 'ziglang==0.14.1', 'python', '-m', 'ziglang', 'c++',
                '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-I', str(FIRMWARE), '-I', str(TESTS / 'dual_fw_stub')]
    records = []

    def run(label, command, fail_at=None):
        env = os.environ.copy()
        env.pop('DUAL_FAIL_AT', None)
        if fail_at is not None:
            env['DUAL_FAIL_AT'] = str(fail_at)
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=240)
        text = result.stdout + result.stderr
        (out / (label + '.log')).write_text(
            'COMMAND ' + subprocess.list2cmdline(command) + '\nEXIT ' + str(result.returncode) + '\n' + text,
            encoding='utf-8')
        record = {'label': label, 'fail_at': fail_at, 'exit_code': result.returncode,
                  'pass_lines': [line for line in result.stdout.splitlines() if line.startswith('PASS ')]}
        records.append(record)
        print(label, result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError(label + ' failed\n' + text)
        return result.stdout

    try:
        protocol = out / 'dual_fw_protocol.exe'
        normal = out / 'dual_fw_sketch.exe'
        empty = out / 'dual_fw_empty.exe'
        run('protocol_compile', compiler + [str(TESTS / 'dual_fw_protocol_test.cpp'), '-o', str(protocol)])
        run('protocol', [str(protocol), 'all'])
        run('hal_compile', compiler + [str(TESTS / 'dual_fw_sketch_test.cpp'), '-o', str(normal)])
        names = run('hal_list', [str(normal), '--list']).splitlines()
        if not names or len(names) != len(set(names)):
            raise RuntimeError('Empty/duplicate host test discovery')
        matrices = {'startup_failure_matrix': range(1, 8), 'recovery_failure_matrix': range(1, 4),
                    'network_setup_failure_matrix': range(1, 9)}
        for name in names:
            if name.startswith('empty_config'):
                continue
            if name in matrices:
                for index in matrices[name]:
                    run(name + '_' + str(index), [str(normal), name], fail_at=index)
            else:
                run(name, [str(normal), name])
        run('empty_compile', compiler + ['-DDUAL_TEST_EMPTY_CONFIG', str(TESTS / 'dual_fw_sketch_test.cpp'), '-o', str(empty)])
        for name in names:
            if name.startswith('empty_config'):
                run(name, [str(empty), name])
    finally:
        sources = [FIRMWARE / 'tes_dua_model_esp32s3.ino']
        sources += list(TESTS.glob('dual_fw*.cpp')) + [p for p in (TESTS / 'dual_fw_stub').rglob('*') if p.is_file()]
        manifest = {'runs': records, 'failed': sum(run['exit_code'] != 0 for run in records),
                    'sources': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
        (out / 'host_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    hal_count = sum(len(run['pass_lines']) for run in records if run['label'] != 'protocol')
    protocol_count = sum(len(run['pass_lines']) for run in records if run['label'] == 'protocol')
    print(f'PASS: {hal_count} eksekusi HAL, {protocol_count} kasus protokol; simulasi tanpa ESP.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
