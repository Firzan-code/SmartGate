"""Fetch the pinned face and siren AST models with size/SHA256 checks; never starts a device."""
import argparse
import hashlib
import os
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
EXPECTED_SHA256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'
EXPECTED_SIZE = 3758596
DEFAULT_DESTINATION = ROOT / 'ml_engine/models/face_landmarker.task'

# The ONNX file exceeds GitHub's 100 MB per-file limit, so it ships as a release asset.
AST_RELEASE_URL = 'https://github.com/Firzan-code/SmartGate/releases/download/model-siren-ast-v2-20261122/'
AST_FILES = {
    'siren_ast_fp16.onnx': (171407125, '4bac249112a43a7ebb91d9eba4dfe088209cc69dc76876d662405a6a0e134c21'),
    'labels.json': (227, '0584de777bcd601d729df9af6bb0e1d36925ab0409b5bec7e3849db7e30bcdab'),
    'preprocessor_config.json': (297, '8d04ba5a9c6fca5d39d0de2b1fd05ecf79deb589fbba279728bbebac39934231'),
    'training_summary.json': (7353, '0be89150539a11a446e69e8376d34dcc13dffead72db02f3648a7b3a91e5f4ec'),
    'export_check.json': (121, '1dc3666b8e036e0c17fb950e9dc6fd7f1eea1c156a87d414f260931b643dbaeb'),
}
DEFAULT_AST_DIR = ROOT / 'ml_engine/models/siren_ast_v2'
CHUNK = 1 << 20


def _matches(path, size, sha256):
    if path.stat().st_size != size:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest() == sha256


def _fetch(url, size, sha256, destination):
    destination = Path(destination)
    if destination.is_file():
        if _matches(destination, size, sha256):
            return destination
        raise ValueError(f'Model lokal berbeda checksum ({destination.name}); '
                         'pindahkan file tersebut sebelum mengunduh ulang.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.part')
    digest, received = hashlib.sha256(), 0
    try:
        with urlopen(url, timeout=60) as response, partial.open('wb') as handle:
            while received <= size:
                block = response.read(min(CHUNK, size + 1 - received))
                if not block:
                    break
                received += len(block)
                digest.update(block)
                handle.write(block)
        if received != size or digest.hexdigest() != sha256:
            raise ValueError(f'Ukuran/checksum model tidak sesuai ({destination.name}); file tidak disimpan.')
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def fetch_model(destination=DEFAULT_DESTINATION):
    return _fetch(URL, EXPECTED_SIZE, EXPECTED_SHA256, destination)


def fetch_ast_model(directory=DEFAULT_AST_DIR):
    directory = Path(directory)
    for name, (size, sha256) in AST_FILES.items():
        _fetch(AST_RELEASE_URL + name, size, sha256, directory / name)
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest', type=Path, default=DEFAULT_DESTINATION, help='Lokasi model wajah MediaPipe')
    parser.add_argument('--ast-dir', type=Path, default=DEFAULT_AST_DIR, help='Folder model sirene AST')
    args = parser.parse_args(argv)
    try:
        path = fetch_model(args.dest)
        print(f'Model MediaPipe siap (checksum terverifikasi): {path}')
        ast_dir = fetch_ast_model(args.ast_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Unduh model gagal: {exc}\n')
    print(f'Model AST siren_ast_v2 siap (checksum terverifikasi): {ast_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
