import os
import sys

from core.comic import get_comic_dir, get_local_ip, get_txt_file, set_work_dir
from ui.app import app, start_background_tasks


def main():
    target_dir = sys.argv[1] if len(sys.argv) > 1 else None
    base_dir = set_work_dir(target_dir or os.getcwd())
    start_background_tasks()
    local_ip = get_local_ip()

    print("=" * 60)
    print("Comic labeler started")
    print(f"Working directory: {base_dir}")
    print(f"TXT file: {os.path.abspath(get_txt_file())}")
    print(f"Image directory: {os.path.abspath(get_comic_dir())}")
    print("=" * 60)
    print("Open this URL on your phone/browser:")
    print(f"   http://{local_ip}:5000")
    print("=" * 60)
    print("Press Ctrl+C to stop the server")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=False)


if __name__ == '__main__':
    main()
