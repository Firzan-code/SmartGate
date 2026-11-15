"""Read-only local monitoring HTTP endpoints, without device/model startup on import."""
from pathlib import Path
import time

from flask import Flask, Response, jsonify, send_file


def placeholder_jpeg(label='MENUNGGU FRAME KAMERA'):
    import cv2
    import numpy as np
    frame = np.full((480, 980, 3), (25, 22, 20), dtype=np.uint8)
    cv2.putText(frame, label, (32, 225), cv2.FONT_HERSHEY_SIMPLEX, .8, (180, 190, 210), 2)
    cv2.putText(frame, 'Tidak ada gambar kamera aktif. Periksa status vision.', (32, 270),
                cv2.FONT_HERSHEY_SIMPLEX, .55, (130, 140, 155), 1)
    ok, data = cv2.imencode('.jpg', frame)
    if not ok:
        raise RuntimeError('Gagal membuat placeholder JPEG')
    return data.tobytes()


def create_app(runtime):
    app = Flask(__name__, static_folder=None)

    @app.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.get('/')
    def index():
        return send_file(Path(__file__).with_name('static_dashboard.html'), mimetype='text/html')

    @app.get('/api/state')
    def state():
        return jsonify(runtime.snapshot())

    @app.get('/health')
    def health():
        state = runtime.snapshot()
        return jsonify(mode='observation_only', http='ok',
                       vision=state['vision']['status'], audio=state['audio']['status'])

    @app.get('/video_feed')
    def video():
        def frames():
            placeholder = placeholder_jpeg()
            while True:
                jpeg = runtime.get_jpeg() or placeholder
                yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                       str(len(jpeg)).encode('ascii') + b'\r\n\r\n' + jpeg + b'\r\n')
                time.sleep(.08)
        return Response(frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

    return app
