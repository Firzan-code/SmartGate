"""Fetch the pinned MediaPipe model from Google; never starts a device."""
import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen

URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
EXPECTED_SHA256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'
EXPECTED_SIZE = 3758596
DEFAULT_DESTINATION = Path(__file__).resolve().parents[1] / 'ml_engine/models/face_landmarker.task'


def fetch_model(destination=DEFAULT_DESTINATION):
    destination = Path(destination)
    if destination.is_file():
        existing = destination.read_bytes()
        if len(existing) == EXPECTED_SIZE and hashlib.sha256(existing).hexdigest() == EXPECTED_SHA256:
            return destination
        raise ValueError('Model lokal berbeda checksum; pindahkan file tersebut sebelum mengunduh ulang.')
    with urlopen(URL, timeout=60) as response:
        content = response.read(EXPECTED_SIZE + 1)
    if len(content) != EXPECTED_SIZE or hashlib.sha256(content).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Ukuran/checksum model tidak sesuai; file tidak disimpan.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest', type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args(argv)
    try:
        path = fetch_model(args.dest)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Unduh model gagal: {exc}\n')
    print(f'Model MediaPipe siap (checksum terverifikasi): {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
