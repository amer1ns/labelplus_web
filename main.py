import atexit
import os
import signal
import socket
import sys

# CTD 模型預設路徑：把相對路徑解析成絕對路徑（以 main.py 所在目錄為基準），
# 寫入環境變數供 ui/services/ctd_engine.py 使用；已設定過則不覆蓋。
os.environ.setdefault(
    'CTD_MODEL_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 'models', 'comictextdetector.pt.onnx'))

from core.comic import get_comic_dir, get_local_ip, get_txt_file, set_work_dir
from ui.app import app, start_background_tasks

# 預設監聽埠 5000；若被其他程式佔用，啟動時自動往後找可用埠
PREFERRED_PORT = int(os.environ.get('PORT', 5000))


def _port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def find_free_port(preferred):
    """回傳 preferred 或下一個可用埠（最多試 200 個）。"""
    if _port_free(preferred):
        return preferred
    for p in range(preferred + 1, preferred + 200):
        if _port_free(p):
            return p
    return preferred


def _self_cleanup():
    """自我關閉：Ctrl+C / Ctrl+Break / 關閉視窗時確保程序退出，不留殘留。"""
    sys.exit(0)


def main():
    target_dir = sys.argv[1] if len(sys.argv) > 1 else None
    base_dir = set_work_dir(target_dir or os.getcwd())
    start_background_tasks()
    local_ip = get_local_ip()

    port = find_free_port(PREFERRED_PORT)
    if port != PREFERRED_PORT:
        print(f"⚠ 埠 {PREFERRED_PORT} 已被占用，改用埠 {port}")

    # 自我關閉機制：處理 Ctrl+C / Ctrl+Break（關閉視窗），確保無殘留進程。
    # 後台執行緒皆為 daemon，主程序退出時會一併結束。
    signal.signal(signal.SIGINT, _self_cleanup)
    if hasattr(signal, 'SIGBREAK'):  # Ctrl+Break / 關閉 console 視窗
        signal.signal(signal.SIGBREAK, _self_cleanup)
    atexit.register(lambda: print('伺服器已關閉'))

    print("=" * 60)
    print("Comic labeler started")
    print(f"Working directory: {base_dir}")
    print(f"TXT file: {os.path.abspath(get_txt_file())}")
    print(f"Image directory: {os.path.abspath(get_comic_dir())}")
    print("=" * 60)
    print("Open this URL on your phone/browser:")
    print(f"   http://{local_ip}:{port}")
    print("=" * 60)
    print("Press Ctrl+C to stop the server")
    print("=" * 60)

    try:
        app.run(host='0.0.0.0', port=port, debug=False)
    finally:
        print('伺服器已關閉')


if __name__ == '__main__':
    main()
