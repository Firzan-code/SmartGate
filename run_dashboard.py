"""Webcam + MAX9814 Wi-Fi; opsi servo sirene untuk demo meja."""
import argparse
import json
import math
from pathlib import Path
import socket
import sys
import time


def lan_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('192.0.2.1', 9))  # routing lookup, no audio/data sent
        return sock.getsockname()[0]
    except OSError:
        return 'IP-LAPTOP'
    finally:
        sock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0, help='Indeks webcam laptop')
    parser.add_argument('--backend', choices=['dshow', 'auto', 'msmf'], default='dshow', help='Backend webcam Windows')
    parser.add_argument('--no-camera', action='store_true', help='Nonaktifkan kamera untuk diagnosis jaringan')
    parser.add_argument('--enable-servo', action='store_true', help='Aktifkan demo meja sirene -> GPIO42, buka 5 detik, cooldown 10 detik')
    parser.add_argument('--port', type=int, default=5000, help='HTTP dashboard lokal')
    parser.add_argument('--udp-port', type=int, default=5006, help='UDP audio pada jaringan lokal')
    parser.add_argument('--seconds', type=float, default=0., help='Durasi uji, 0 berjalan sampai Ctrl+C')
    parser.add_argument('--report', type=Path, help='Opsional: simpan status akhir JSON, tanpa gambar/audio')
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or args.seconds < 0:
        parser.error('--seconds harus finite dan tidak negatif')
    if not 1 <= args.port <= 65535 or not 1 <= args.udp_port <= 65535 or args.camera < 0:
        parser.error('Port/indeks kamera tidak valid')
    from smart_gate_full.backend.app import create_app
    from smart_gate_full.backend.runtime import MonitorRuntime
    from werkzeug.serving import make_server
    runtime = MonitorRuntime(servo_enabled=args.enable_servo)
    server = None
    exit_code = 0
    try:
        # Bind HTTP before starting native device workers, so an occupied port is safe.
        server = make_server('127.0.0.1', args.port, create_app(runtime), threaded=True)
        server.timeout = .2
        print(f'[DASHBOARD] http://127.0.0.1:{args.port}', flush=True)
        print(f'[ESP] SERVER_IP = {lan_ip()} | UDP {args.udp_port}', flush=True)
        print('[PRIVASI] Webcam lokal, tanpa penyimpanan audio/video. Tidak membuka COM9.', flush=True)
        print('[MODEL] siren_ast_v2 ONNX, jendela audio 3 detik; kedipan bukan identitas/otorisasi.', flush=True)
        if not args.no_camera:
            print('[KAMERA] Mengaktifkan webcam laptop untuk uji ini; Ctrl+C untuk berhenti.', flush=True)
        runtime.start(camera_enabled=not args.no_camera, camera_index=args.camera,
                      camera_backend=args.backend, udp_port=args.udp_port)
        started = time.monotonic()
        while not args.seconds or time.monotonic() - started < args.seconds:
            server.handle_request()
    except KeyboardInterrupt:
        print('\n[STOP] Dihentikan pengguna.', flush=True)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'[ERROR] {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        exit_code = 1
    finally:
        try:
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(runtime.snapshot(), indent=2, allow_nan=False), encoding='utf-8')
        except Exception as exc:
            print(f'[ERROR REPORT] {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            exit_code = 1
        finally:
            try:
                runtime.stop()
            except Exception as exc:
                print(f'[ERROR STOP] {exc}', file=sys.stderr, flush=True)
                exit_code = 1
            finally:
                if server is not None:
                    server.server_close()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
