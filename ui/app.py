import os

from flask import Flask

from ui.blueprints.config_api import config_bp
from ui.blueprints.dialogues import dialogues_bp
from ui.blueprints.images import images_bp
from ui.blueprints.ocr import ocr_bp
from ui.blueprints.pages import pages_bp
from ui.blueprints.review import review_bp
from ui.services.prewarm import start_background_tasks


def create_app():
    app = Flask(__name__)

    @app.after_request
    def _no_cache_html(resp):
        if resp.content_type and resp.content_type.startswith('text/html'):
            resp.headers['Cache-Control'] = 'no-store'
            resp.headers['Pragma'] = 'no-cache'
        return resp

    app.register_blueprint(pages_bp)
    app.register_blueprint(dialogues_bp)
    app.register_blueprint(images_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(ocr_bp)
    app.register_blueprint(review_bp)
    return app


app = create_app()


if __name__ == '__main__':
    import socket as _socket
    import signal as _signal
    from core.comic import get_comic_dir, get_txt_file
    from utils.network import get_local_ip

    def _free(p):
        s = _socket.socket()
        try:
            s.bind(('0.0.0.0', p))
            return True
        except OSError:
            return False
        finally:
            s.close()

    port = 5000
    if not _free(port):
        for p in range(5001, 5201):
            if _free(p):
                port = p
                break
    if port != 5000:
        print(f"⚠ 埠 5000 已被占用，改用埠 {port}")

    local_ip = get_local_ip()
    print("=" * 60)
    print("Comic labeler started")
    print(f"TXT file: {os.path.abspath(get_txt_file())}")
    print(f"Image directory: {os.path.abspath(get_comic_dir())}")
    print("=" * 60)
    print("Open this URL on your phone/browser:")
    print(f"   http://{local_ip}:{port}")
    print("=" * 60)
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    start_background_tasks()
    app.run(host='0.0.0.0', port=port, debug=False)
