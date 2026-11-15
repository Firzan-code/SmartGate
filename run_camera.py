"""Demo lokal OpenCV + MediaPipe + EAR; tidak mengirim perintah gerbang."""
import argparse
import json
import math
from pathlib import Path
import sys
import time

import cv2

from ml_engine.vision_ear import EARLivenessDetector


WINDOW_TITLE = 'Smart Gate - Kamera dan EAR (Q: keluar, R: reset)'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--camera', type=int, default=0, help='Indeks webcam, default 0')
    source.add_argument('--video', type=Path, help='Video lokal; timestamp berasal dari FPS video')
    source.add_argument('--image', type=Path, help='Gambar lokal untuk pemeriksaan overlay saja')
    parser.add_argument('--backend', choices=['auto', 'dshow', 'msmf'], default='auto')
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=480)
    parser.add_argument('--ear-close', type=float, default=0.21)
    parser.add_argument('--ear-open', type=float, default=0.25)
    parser.add_argument('--headless', action='store_true', help='Tidak membuka jendela; wajib dibatasi')
    parser.add_argument('--seconds', type=float, default=0, help='Batas durasi wall-clock, 0=tanpa batas')
    parser.add_argument('--max-frames', type=int, default=0)
    parser.add_argument('--snapshot', type=Path, help='Simpan SATU frame terakhir hanya bila diminta')
    parser.add_argument('--report', type=Path, help='Simpan metrik JSON tanpa rekaman video')
    args = parser.parse_args(argv)
    if (args.width < 1 or args.height < 1 or args.max_frames < 0
            or not math.isfinite(args.seconds) or args.seconds < 0):
        parser.error('Resolusi/batas durasi atau frame tidak valid')
    if args.headless and not args.image and not args.seconds and not args.max_frames:
        parser.error('--headless memerlukan --seconds atau --max-frames')
    detector = None
    capture = None
    last_frame = None
    processing_ms_total = 0.0
    frames = faces = max_blinks = 0
    last_state = None
    read_error = None
    started = time.perf_counter()
    try:
        detector = EARLivenessDetector(ear_threshold=args.ear_close, open_threshold=args.ear_open)
        print('[VISION] Model:', detector.get_state()['backend'], flush=True)
        print('[VISION] Lokal, tanpa rekaman otomatis. Identitas belum diverifikasi.', flush=True)
        if args.image:
            frame_image = cv2.imread(str(args.image))
            if frame_image is None:
                raise RuntimeError(f'Gambar tidak dapat dibaca: {args.image}')
        else:
            backend = {'auto': cv2.CAP_ANY, 'dshow': cv2.CAP_DSHOW, 'msmf': cv2.CAP_MSMF}[args.backend]
            capture = cv2.VideoCapture(str(args.video)) if args.video else cv2.VideoCapture(args.camera, backend)
            if not capture.isOpened():
                raise RuntimeError('Kamera/video tidak dapat dibuka. Periksa izin kamera, indeks, atau --backend dshow.')
            if not args.video:
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
                capture.set(cv2.CAP_PROP_FPS, 30)
            video_fps = capture.get(cv2.CAP_PROP_FPS) if args.video else 0
            if args.video and not 0 < video_fps < 1000:
                raise RuntimeError('FPS video tidak valid; tidak bisa menentukan durasi kedipan')
        if not args.headless:
            cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(WINDOW_TITLE, args.width + 340, max(args.height, 480))
        previous_blinks = 0
        loop_started = time.perf_counter()
        while True:
            if args.image:
                frame = frame_image
            else:
                ok, frame = capture.read()
                if not ok or frame is None:
                    if args.video:
                        break
                    read_error = 'Kamera berhenti menghasilkan frame'
                    raise RuntimeError(read_error)
            timestamp = frames / video_fps if args.video else time.monotonic()
            annotated, state = detector.process_frame(frame, timestamp=timestamp)
            frames += 1
            faces += int(state['face_detected'])
            max_blinks = max(max_blinks, state['total_blinks'])
            processing_ms_total += state['processing_ms']
            last_frame, last_state = annotated, state
            if state['total_blinks'] != previous_blinks:
                previous_blinks = state['total_blinks']
                print(f"[KEDIPAN] total={previous_blinks}; jendela={state['blink_counter']}; terpenuhi={state['liveness_verified']}", flush=True)
            if not args.headless:
                cv2.imshow(WINDOW_TITLE, annotated)
                while True:
                    key = cv2.waitKey(20 if args.image else 1) & 0xFF
                    exit_requested = (key in (ord('q'), ord('Q'), 27)
                                      or cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1)
                    if exit_requested:
                        break
                    if key in (ord('r'), ord('R')):
                        detector.reset_verification()
                    # Keep the one processed image visible without generating blink frames.
                    if not args.image or (args.seconds and time.perf_counter() - loop_started >= args.seconds):
                        break
                if exit_requested:
                    break
            if args.image or (args.max_frames and frames >= args.max_frames):
                break
            if args.seconds and time.perf_counter() - loop_started >= args.seconds:
                break
        if frames == 0:
            raise RuntimeError('Tidak ada frame yang berhasil diproses')
        if args.snapshot:
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(args.snapshot), last_frame):
                raise RuntimeError(f'Gagal menulis snapshot: {args.snapshot}')
        report = {
            'source_type': 'image' if args.image else 'video' if args.video else 'camera',
            'source': str(args.image or args.video or args.camera),
            'frames_processed': frames, 'frames_with_face': faces,
            'observed_total_blinks': max_blinks,
            'mean_inference_and_ear_ms': round(processing_ms_total / frames, 2),
            'elapsed_sec_including_startup': round(time.perf_counter() - started, 2),
            'last_state': last_state,
            'limitation': 'Kedipan bukan verifikasi identitas atau bukti anti-replay.',
        }
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        print(json.dumps(report, indent=2, allow_nan=False), flush=True)
        return 0
    except (RuntimeError, ValueError, OSError, cv2.error) as exc:
        print(f'[ERROR VISION] {exc}', file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('[VISION] Dihentikan pengguna.', flush=True)
        return 0
    finally:
        if capture is not None:
            capture.release()
        if detector is not None:
            detector.close()
        if not args.headless:
            cv2.destroyAllWindows()


if __name__ == '__main__':
    raise SystemExit(main())
