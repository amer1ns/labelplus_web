import json
import os

from core.comic import get_comic_dir


def _cache_dir():
    d = os.path.join(get_comic_dir(), '.cache', 'ocr')
    os.makedirs(d, exist_ok=True)
    return d


def _cache_path(img):
    return os.path.join(_cache_dir(), img + '.json')


def load_originals(img):
    """Return {marker_id: original_text} for an image (empty dict if none)."""
    p = _cache_path(img)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_original(img, marker_id, text):
    """Set (or clear, when text empty) the original text for a marker. Returns the full dict."""
    data = load_originals(img)
    text = (text or '').strip()
    key = str(marker_id)
    if text:
        data[key] = text
    else:
        data.pop(key, None)
    with open(_cache_path(img), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def save_originals(img, mapping):
    """Overwrite ALL original texts for an image from `{marker_id: text}`.

    The cache file is replaced wholesale, so stale entries from a previous
    auto-OCR run are dropped. Empty/blank texts are skipped. Returns the dict
    actually written."""
    data = {str(k): (v or '').strip() for k, v in (mapping or {}).items() if v}
    with open(_cache_path(img), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def clear_originals(img):
    """Drop all saved original texts for an image (auto OCR replaces a page)."""
    p = _cache_path(img)
    if os.path.exists(p):
        try:
            os.remove(p)
        except Exception:
            pass
