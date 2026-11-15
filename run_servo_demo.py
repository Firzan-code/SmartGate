"""Demo SG90: wajah + kedua mata terbuka 5 detik; default simulasi tanpa gerak."""
import argparse
import ipaddress
import math
from pathlib import Path
import sys
import time


def create_app(controller, detector):
    from flask import Flask, Response, jsonify, send_file
    app = Flask(__name__, static_folder=None)

    @app.after_request
    def privacy(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'"
        return response

    @app.get('/')
    def index():
        return send_file(Path(__file__).parent / 'smart_gate_full/backend/servo_dashboard.html')

    @app.get('/api/state')
    def state():
        return jsonify(vision=detector.get_state(), servo=controller.snapshot(), authorized=False)

    @app.get('/video_feed')
    def video():
        from smart_gate_full.backend.app import placeholder_jpeg
        def frames():
            placeholder = placeholder_jpeg()
            while True:
                jpeg = detector.get_jpeg_frame() or placeholder
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
                time.sleep(.1)
        return Response(frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable-servo', action='store_true', help='AKTIFKAN gerak fisik SG90; tanpa horn/palang')
    parser.add_argument('--esp-ip', help='IPv4 ESP dari Serial Monitor; wajib untuk gerak fisik')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--backend', choices=['dshow', 'auto', 'msmf'], default='dshow')
    parser.add_argument('--port', type=int, default=5001)
    parser.add_argument('--seconds', type=float, default=0., help='0 sampai Ctrl+C')
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or args.seconds < 0 or args.camera < 0 or not 1 <= args.port <= 65535:
        parser.error('Durasi/indeks/port tidak valid')
    if args.enable_servo and not args.esp_ip:
        parser.error('--enable-servo perlu --esp-ip')
    if args.esp_ip:
        try:
            address = ipaddress.IPv4Address(args.esp_ip)
            if address.is_unspecified or address.is_multicast or address.is_loopback or int(address) == 0xffffffff:
                raise ValueError('Alamat bukan ESP LAN')
        except ValueError:
            parser.error('--esp-ip harus IPv4 unicast ESP pada LAN privat')
    from smart_gate_full.backend.servo_demo import ServoController
    from smart_gate_full.backend.servo_link import ServoLink
    from smart_gate_full.backend.servo_camera import ServoVision
    from werkzeug.serving import make_server
    link = detector = server = controller = None
    exit_code = 0
    try:
        if args.enable_servo:
            print('[PERINGATAN] SERVO AKTIF: ARM -> target90, OPEN -> target110 sekali. Lepas horn/palang!', flush=True)
            link = ServoLink(args.esp_ip)
        controller = ServoController(link)
        detector = ServoVision(controller, camera_index=args.camera, backend=args.backend)
        server = make_server('127.0.0.1', args.port, create_app(controller, detector), threaded=True)
        server.timeout = .02
        print(f'[DASHBOARD] http://127.0.0.1:{args.port}', flush=True)
        print('[MODE] ' + ('HARDWARE SERVO / UDP5010' if link else 'SIMULASI: TIDAK MENGIRIM PERINTAH SERVO'), flush=True)
        print('[KAMERA] Webcam lokal mulai, tanpa rekaman. Kedipan mereset 5 detik. Ctrl+C berhenti.', flush=True)
        detector.start()
        started = time.monotonic()
        while not args.seconds or time.monotonic() - started < args.seconds:
            controller.tick(time.monotonic())
            server.handle_request()
    except KeyboardInterrupt:
        print('\n[STOP] Demo dihentikan.', flush=True)
    except Exception as exc:
        print(f'[ERROR] {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        exit_code = 1
    finally:
        if controller is not None:
            with controller.lock:
                controller.blocked = True  # No late camera callback may send after shutdown.
        if link is not None:
            try:
                if not link.disarm(time.monotonic()):
                    print('[DISARM] Tidak terkirim; ESP watchdog melepas PWM tanpa tutup otomatis.', file=sys.stderr)
                    exit_code = 1
            except Exception as exc:
                print(f'[DISARM] {exc}; ESP watchdog melepas PWM tanpa tutup otomatis.', file=sys.stderr)
                exit_code = 1
            finally:
                try:
                    link.close()
                except Exception as exc:
                    print(f'[UDP CLOSE] {exc}', file=sys.stderr)
                    exit_code = 1
        try:
            if detector is not None:
                detector.close()
        except Exception as exc:
            print(f'[CAMERA STOP] {exc}', file=sys.stderr)
            exit_code = 1
        finally:
            if server is not None:
                server.server_close()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
