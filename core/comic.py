import json
import os
import re
from pathlib import Path

from utils.network import get_local_ip

SCRIPT_DIR = Path.cwd().resolve()

# App-level settings (marker size, OCR / translate API config) live in the app
# folder itself — next to the .py files — NOT the comic folder.  get_comic_dir()
# follows the folder passed to start_server.bat, which changes per comic; tying
# config.json to it made API settings "disappear" whenever a different comic
# folder was opened.  __file__ keeps this independent of the working directory.
# The file is named api_config.json so the saved API settings are obvious.
CONFIG_PATH = os.path.join(str(Path(__file__).resolve().parent.parent), 'api_config.json')
IMG_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff', '.avif'}

TXT_FILE = None
COMIC_DIR = None


def get_base_dir():
    return Path.cwd().resolve()


def set_work_dir(base_dir=None):
    target = Path(base_dir or get_base_dir()).expanduser().resolve()
    os.chdir(target)
    global SCRIPT_DIR, TXT_FILE, COMIC_DIR
    SCRIPT_DIR = target
    TXT_FILE = None
    COMIC_DIR = None
    return str(target)


def ensure_txt_exists(script_dir=None):
    """找不到「翻译_0.txt」時，掃描目錄內圖片（不含子目錄）並按格式生成 txt"""
    base_dir = Path(script_dir or get_base_dir()).resolve()
    target = base_dir / "翻译_0.txt"
    if target.exists():
        print(target)
        return str(target)

    imgs = sorted(
        p.name for p in base_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMG_EXTS
    )
    if not imgs:
        raise FileNotFoundError(f"在 {base_dir} 中既没有找到 txt 文件，也没有找到圖片文件")

    content = "1,0\n-\n框内\n框外\n-\nDefault Comment\n You can edit me\n\n"
    for name in imgs:
        content += f">>>>>>>>[{name}]<<<<<<<<\n\n"
    target.write_text(content, encoding='utf-8')
    print(f"未找到翻译_0.txt，已根据 {len(imgs)} 張圖片自動生成：{target}")
    return str(target)


def get_txt_file():
    global TXT_FILE
    if TXT_FILE is None:
        TXT_FILE = ensure_txt_exists(SCRIPT_DIR)
    return TXT_FILE


def get_comic_dir():
    global COMIC_DIR
    if COMIC_DIR is None:
        COMIC_DIR = SCRIPT_DIR
    return COMIC_DIR


def get_config_path():
    """Absolute path of the app-level api_config.json (project folder)."""
    return CONFIG_PATH


def read_config():
    """Load the app config JSON.  Falls back to the legacy comic-dir config.json
    once, so settings saved before the move are still picked up. If no config
    exists at all, copy api_config.example.json (the uploaded, key-less template)
    into place so the app always has a valid config to start from."""
    for path in (CONFIG_PATH, os.path.join(get_comic_dir(), 'config.json')):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass

    # 沒有任何設定檔 → 從範本複製一份（範本不含 API Key）
    example = os.path.join(os.path.dirname(CONFIG_PATH), 'api_config.example.json')
    if os.path.exists(example):
        try:
            import shutil
            shutil.copyfile(example, CONFIG_PATH)
            print(f"未找到 api_config.json，已從 {os.path.basename(example)} 複製一份（請在網頁 🅾 OCR 設定填入 API Key）")
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def write_config(cfg):
    """Write the app config JSON into the app folder."""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def parse_all_comics(txt_path=None):
    path = txt_path or get_txt_file()
    if not os.path.exists(path):
        print(f"Warning: TXT file not found: {path}")
        return {}

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = r'>>>>>>>>\[([^\]]+\.[a-zA-Z0-9]+)\]<<<<<<<<\s*(.*?)(?=>>>>>>>>|$)'
    matches = re.findall(pattern, content, re.DOTALL)

    result = {}
    for img_name, block_content in matches:
        dialogues = []
        dialogue_pattern = r'----------------\[(\d+)\]----------------\[([\d.]+),([\d.]+),([12])\]\s*(.*?)(?=----------------\[\d+\]----------------|$)'
        matches_dialogues = re.findall(dialogue_pattern, block_content, re.DOTALL)

        for idx, x, y, inside_flag, text in matches_dialogues:
            clean_text = text.strip()
            dialogues.append({
                'id': int(idx),
                'x': float(x),
                'y': float(y),
                'inside': int(inside_flag),
                'text': clean_text,
            })

        result[img_name] = dialogues
        print(f"  {img_name}: found {len(dialogues)} dialogues")

    print(f"Parsed {len(result)} images")
    return result


def save_all_comics(txt_path=None, data=None):
    path = txt_path or get_txt_file()
    new_content = "1,0\n"
    new_content += "-\n"
    new_content += "框内\n"
    new_content += "框外\n"
    new_content += "-\n"
    new_content += "Default Comment\n"
    new_content += " You can edit me\n\n"

    for img_name, dialogues in (data or {}).items():
        new_content += f">>>>>>>>[{img_name}]<<<<<<<<\n"
        for d in dialogues:
            inside_flag = 1 if int(d.get('inside', 1)) == 1 else 2
            new_content += f"----------------[{d['id']}]----------------[{d['x']:.3f},{d['y']:.3f},{inside_flag}]\n"
            if d['text']:
                new_content += f"{d['text']}\n"
            new_content += "\n"

    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)


__all__ = [
    "SCRIPT_DIR",
    "IMG_EXTS",
    "TXT_FILE",
    "COMIC_DIR",
    "ensure_txt_exists",
    "get_base_dir",
    "set_work_dir",
    "get_txt_file",
    "get_comic_dir",
    "get_config_path",
    "read_config",
    "write_config",
    "parse_all_comics",
    "save_all_comics",
    "get_local_ip",
]
