"""復習帳 (review notebook) — personal Japanese study SRS store.

A difficulty captured from the editor (original text + translation) is saved
here as a review item. Items are spaced-repetition scheduled with a simplified
SM-2 algorithm:

    status: new (新學) -> learning/review (複習中) -> mastered (已掌握, 偶爾複習)
    grades: again (忘了) / hard (困難) / good (記得) / easy (很熟)

Storage is a plain JSON file under 復習帳/ next to the app (NOT the comic
folder), so the notebook survives switching between comic folders — same
convention as api_config.json.
"""

import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from ui.services.translate import chat, resolve_config

try:
    from core.comic import read_config, get_comic_dir
except Exception:  # pragma: no cover
    read_config = None
    get_comic_dir = None

# Interval (days) at which an item is considered "mastered" (occasional review).
MASTERED_DAYS = 30

REVIEW_DIR = Path(__file__).resolve().parent.parent.parent / '復習帳'
ITEMS_PATH = REVIEW_DIR / 'items.json'
README_PATH = REVIEW_DIR / 'README.md'

_STATUS_LABELS = {'new': '新學', 'learning': '複習中', 'review': '複習中', 'mastered': '已掌握'}

BREAKDOWN_SYSTEM_PROMPT = (
    '你是日語學習助手，幫我把這句日文拆解成可以複習的考點。\n'
    '重要背景：\n'
    '- 原文通常來自 OCR 辨識，可能含有錯誤（假名混淆、漢字錯字、濁音／半濁音、'
    '促音、長音、拗音漏寫、標點、字元替換等）。\n'
    '- 譯文是用戶確認正確的翻譯，請以譯文為基準，推測原文真正應該怎麼寫。\n'
    '步驟：\n'
    '1. 先依譯文（及上下文）推測並修正原文的 OCR 錯誤，得到 corrected_original。'
    '只修正錯字／漏字／多字這類辨識錯誤，不要改寫句子的結構、語氣、時態或措辭；'
    '如果沒有把握或不確定，corrected_original 就與原文相同。\n'
    '2. 用修正後的原文拆解：只輸出真正有學習價值的語法點、句型、慣用表達；'
    '跳過過於基礎的內容（例如「おれ＝我」這類基礎詞彙、は/が 等助詞的基本用法）。\n'
    '3. 如果句子沒有特別值得記的點，grammar 輸出空陣列。\n'
    '4. 全部用繁體中文說明。\n'
    '只輸出 JSON（不要 markdown 程式碼塊），格式：\n'
    '{"corrected_original": "修正後的原文（無把握就與原文相同）", '
    '"grammar": ["語法點1（含簡短說明）", "語法點2", ...], '
    '"meaning": "整句含義與語氣／語境的簡要解析", '
    '"example": "一句類似用法的例句（日文＋中文）", '
    '"confusion": "容易混淆或值得注意的地方（沒有就給空字串）"}'
)


# ---------------------------------------------------------------------------
# 資料夾與檔案
# ---------------------------------------------------------------------------

def _ensure_dir():
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    if not README_PATH.exists():
        README_PATH.write_text(
            '# 復習帳 📚\n\n'
            '這是「困難標記」收集的個人日語複習資料庫，由程式自動維護：\n\n'
            '- `items.json` — 所有考點與複習排程（間隔複習 SM-2）\n'
            '- 在編輯框點 ⭐ 即可把「原文＋譯文」存進來，可一鍵 AI 拆解語法／含義\n'
            '- 打開 `http://<本機IP>:5000/review` 進行每日複習\n\n'
            '狀態：新學（沒學過）→ 複習中（按間隔複習）→ 已掌握（≥30 天，偶爾複習）。\n',
            encoding='utf-8')
    return REVIEW_DIR


def _load_items():
    if not ITEMS_PATH.exists():
        return []
    try:
        with open(ITEMS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        items = data.get('items') if isinstance(data, dict) else data
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _save_items(items):
    _ensure_dir()
    with open(ITEMS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'items': items}, f, ensure_ascii=False, indent=2)


def _current_manga_name():
    """Return the basename of the current comic folder (for filtering)."""
    if get_comic_dir is None:
        return ''
    try:
        return os.path.basename(get_comic_dir() or '')
    except Exception:
        return ''


def _snapshot_context(img, shared):
    """考點自包含的來源快照：漫畫資料夾名 + 圖片名 + 標號位置。

    考點一旦存入就不再依賴「目前圖片的 img+marker_id」來定位；即使圖片
    標號重排、刪除，考點仍保有完整的出處資訊。
    """
    manga_name = (shared.get('manga_name') or '').strip()
    if not manga_name:
        try:
            from core.comic import get_comic_dir
            manga_name = os.path.basename(get_comic_dir() or '')
        except Exception:
            manga_name = ''
    marker_x = shared.get('marker_x')
    marker_y = shared.get('marker_y')
    try:
        marker_x = float(marker_x) if marker_x is not None else None
    except Exception:
        marker_x = None
    try:
        marker_y = float(marker_y) if marker_y is not None else None
    except Exception:
        marker_y = None
    return {
        'manga_name': manga_name,
        'page_name': (img or '').strip(),
        'marker_x': marker_x,
        'marker_y': marker_y,
    }


def _new_item(img, marker_id, original, translation, note='', point='', shared=None):
    shared = shared or {}
    ctx = _snapshot_context(img, shared)
    return {
        'id': uuid.uuid4().hex[:12],
        'img': img or '',
        'marker_id': marker_id,
        'manga_name': ctx['manga_name'],
        'page_name': ctx['page_name'],
        'marker_x': ctx['marker_x'],
        'marker_y': ctx['marker_y'],
        'point': (point or '').strip(),          # 考點標題（如「〜わけにはいかない」）
        'original': (original or '').strip(),
        'translation': (translation or '').strip(),
        'note': (note or '').strip(),
        'grammar': '',
        'meaning': '',
        'example': '',
        'confusion': '',
        'status': 'new',
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'updated_at': datetime.now().isoformat(timespec='seconds'),
        'due': date.today().isoformat(),
        'reps': 0,
        'interval_days': 0,
        'ease': 2.5,
        'lapses': 0,
        'last_reviewed': None,
        'history': [],
    }


# ---------------------------------------------------------------------------
# 查詢
# ---------------------------------------------------------------------------

def get_items():
    items = _load_items()
    manga = _current_manga_name()
    if manga:
        items = [it for it in items
                 if it.get('manga_name') in (manga, '', None)]
    return items


def find_item(img, marker_id):
    manga = _current_manga_name()
    for it in _load_items():
        if it.get('img') == img and it.get('marker_id') == marker_id:
            if not manga or it.get('manga_name') in (manga, '', None):
                return it
    return None


def _find_by_id(items, item_id):
    for it in items:
        if it.get('id') == item_id:
            return it
    return None


def _find_by_key(items, img, marker_id, point):
    """同一標號、同一考點標題 → 視為同一張卡（更新）；point 空則退回舊行為（一標號一卡）。"""
    point = (point or '').strip()
    for it in items:
        if (it.get('img') == img and it.get('marker_id') == marker_id
                and (it.get('point') or '').strip() == point):
            return it
    return None


def _reset_srs(it):
    """句子內容變了 → 重新學。"""
    it['status'] = 'new'
    it['reps'] = 0
    it['interval_days'] = 0
    it['ease'] = 2.5
    it['lapses'] = 0
    it['due'] = date.today().isoformat()
    it['last_reviewed'] = None


# ---------------------------------------------------------------------------
# 新增／更新
# ---------------------------------------------------------------------------

def capture_items(img, marker_id, original, translation, entries=None, shared=None, removed_ids=None):
    """Save one or more 考點 (knowledge points) for a marker. One sentence can
    contain several difficulties — each entry becomes its own review card.

    entries: [{'item_id'?, 'point', 'grammar', 'note'}, ...]
    shared:  {'meaning', 'example', 'confusion'} — sentence-level fields copied
             onto every card.
    removed_ids: item ids whose rows the user deleted in the modal.
    Returns (items_in_entry_order, created_flags).
    """
    entries = entries if entries else [{}]
    items = _load_items()
    orig = (original or '').strip()
    trans = (translation or '').strip()
    shared = shared or {}
    removed_ids = removed_ids or []

    # 使用者刪掉的考點列 → 移除（僅限同 img+marker 的卡片）
    if removed_ids:
        rm = set(removed_ids)
        items = [it for it in items
                 if not (it.get('id') in rm and it.get('img') == img and it.get('marker_id') == marker_id)]

    results = []
    created_flags = []
    for e in entries:
        point = (e.get('point') or '').strip()
        it = None
        eid = e.get('item_id')
        if eid:
            it = _find_by_id(items, eid)
        if it is None:
            it = _find_by_key(items, img, marker_id, point)
        if it is None:
            it = _new_item(img, marker_id, orig, trans, note=e.get('note') or '',
                           point=point, shared=shared)
            items.append(it)
            created_flags.append(True)
        else:
            created_flags.append(False)
            content_changed = ((it.get('original') or '') != orig
                               or (it.get('translation') or '') != trans)
            # 補上來源快照欄位（舊資料沒有則補；已有的保留原樣）
            ctx = _snapshot_context(img, shared)
            for k in ('manga_name', 'page_name', 'marker_x', 'marker_y'):
                if it.get(k) in (None, '', -1):
                    it[k] = ctx[k]
            it['original'] = orig
            it['translation'] = trans
            it['point'] = point
            it['note'] = (e.get('note') or '').strip()
            if content_changed:
                _reset_srs(it)
        if 'grammar' in e:
            it['grammar'] = (e.get('grammar') or '').strip()
        for k in ('meaning', 'example', 'confusion'):
            if k in shared:
                it[k] = (shared.get(k) or '').strip()
        it['updated_at'] = datetime.now().isoformat(timespec='seconds')
        results.append(it)

    _save_items(items)
    return results, created_flags


def capture_item(img, marker_id, original, translation, note='', point='', grammar='',
                 meaning='', example='', confusion='', ai=False, cfg=None):
    """單一考點包裝（相容舊呼叫）。"""
    entries = [{'point': point, 'grammar': grammar, 'note': note}]
    shared = {'meaning': meaning, 'example': example, 'confusion': confusion}
    if ai:
        bd = breakdown(original, translation, cfg)
        if bd:
            shared = {k: bd.get(k, '') for k in ('meaning', 'example', 'confusion')}
            if not grammar:
                entries[0]['grammar'] = bd.get('grammar', '')
    items, flags = capture_items(img, marker_id, original, translation, entries, shared)
    return (items[0] if items else None), (flags[0] if flags else False)


def _existing_id(items, img, marker_id):
    """Return the id of an existing item with the same img+marker (or None)."""
    for it in items:
        if it.get('img') == img and it.get('marker_id') == marker_id:
            return it.get('id')
    return None


def update_item(item_id, fields):
    items = _load_items()
    it = _find_by_id(items, item_id)
    if not it:
        return None
    for k in ('point', 'original', 'translation', 'note', 'grammar', 'meaning', 'example', 'confusion'):
        if k in fields:
            it[k] = (fields.get(k) or '').strip()
    it['updated_at'] = datetime.now().isoformat(timespec='seconds')
    _save_items(items)
    return it


def delete_item(item_id):
    items = _load_items()
    before = len(items)
    items = [it for it in items if it.get('id') != item_id]
    if len(items) != before:
        _save_items(items)
        return True
    return False


def migrate_marker_ids(img, mapping, deleted_ids=None):
    """標號重排後，遷移同一張圖的考點 marker_id（舊 id → 新 id）。

    ``mapping``: {舊 marker_id 字串: 新 marker_id int}，只含「有變化」的 id。
    ``deleted_ids``: 本次被刪除的標號 id。這些標號的考點無新歸屬，保留原樣
    並回傳其 item id 供前端告知用戶。

    回傳 ``(changed, orphan_ids)``。
    """
    deleted_ids = [str(int(d)) for d in (deleted_ids or [])]
    items = _load_items()
    changed = 0
    orphan = []
    for it in items:
        if it.get('img') != img:
            continue
        mid = str(it.get('marker_id'))
        if mid in mapping:
            new_mid = int(mapping[mid])
            if int(it.get('marker_id') or 0) != new_mid:
                it['marker_id'] = new_mid
                it['updated_at'] = datetime.now().isoformat(timespec='seconds')
                changed += 1
        elif mid in deleted_ids:
            # 對應的標號被刪除 → 無歸屬：marker_id 設 -1 避免與新標號衝突，
            # 保留資料並告知用戶（可在復習帳列表中看到並處理）。
            if int(it.get('marker_id') or 0) != -1:
                it['marker_id'] = -1
                it['updated_at'] = datetime.now().isoformat(timespec='seconds')
                changed += 1
            orphan.append(it.get('id'))
    if changed:
        _save_items(items)
    return changed, orphan


# ---------------------------------------------------------------------------
# 間隔複習 (SM-2 簡化版)
# ---------------------------------------------------------------------------

def _sm2_interval(reps, interval, ease):
    if reps <= 1:
        return 1
    if reps == 2:
        return 6
    return max(1, int(round(interval * ease)))


def grade_item(item_id, grade):
    """Apply a review grade and reschedule. Returns the updated item or None."""
    items = _load_items()
    it = _find_by_id(items, item_id)
    if not it:
        return None
    if grade not in ('again', 'hard', 'good', 'easy'):
        grade = 'again'

    today = date.today()
    ease = float(it.get('ease', 2.5))
    interval = int(it.get('interval_days', 0) or 0)
    reps = int(it.get('reps', 0) or 0)

    if grade == 'again':
        reps = 0
        interval = 0
        ease = max(1.3, ease - 0.2)
        it['lapses'] = int(it.get('lapses', 0) or 0) + 1
        due = today
    elif grade == 'hard':
        reps += 1
        interval = max(1, int(round(interval * 1.2))) if interval > 0 else 1
        ease = max(1.3, ease - 0.15)
        due = today + timedelta(days=interval)
    elif grade == 'good':
        reps += 1
        interval = _sm2_interval(reps, interval, ease)
        due = today + timedelta(days=interval)
    else:  # easy
        reps += 1
        interval = max(2, int(round(_sm2_interval(reps, interval, ease) * 1.3)))
        ease = min(3.5, ease + 0.15)
        due = today + timedelta(days=interval)

    it['reps'] = reps
    it['interval_days'] = interval
    it['ease'] = round(ease, 2)
    it['last_reviewed'] = today.isoformat()
    it['due'] = due.isoformat()
    it['status'] = 'learning' if interval == 0 else ('mastered' if interval >= MASTERED_DAYS else 'review')
    it['updated_at'] = datetime.now().isoformat(timespec='seconds')
    it.setdefault('history', []).append({'date': today.isoformat(), 'grade': grade})

    _save_items(items)
    return it


def set_item_state(item_id, action):
    """Manual state tweaks: master (已掌握) / relearn (重新學習) / skip (明天再複習)."""
    items = _load_items()
    it = _find_by_id(items, item_id)
    if not it:
        return None
    today = date.today()
    if action == 'master':
        it['status'] = 'mastered'
        it['interval_days'] = MASTERED_DAYS
        it['due'] = (today + timedelta(days=MASTERED_DAYS)).isoformat()
    elif action == 'relearn':
        it['status'] = 'new'
        it['reps'] = 0
        it['interval_days'] = 0
        it['ease'] = 2.5
        it['lapses'] = 0
        it['due'] = today.isoformat()
    elif action == 'skip':
        it['due'] = (today + timedelta(days=1)).isoformat()
    else:
        return None
    it['updated_at'] = datetime.now().isoformat(timespec='seconds')
    _save_items(items)
    return it


# ---------------------------------------------------------------------------
# 儀表板（每天啟動時的自動標記）
# ---------------------------------------------------------------------------

def dashboard():
    today = date.today().isoformat()
    items = _load_items()
    manga = _current_manga_name()
    if manga:
        items = [it for it in items
                 if it.get('manga_name') in (manga, '', None)]
    new_count = review_count = mastered_count = due_count = 0
    queue = []
    for it in items:
        status = it.get('status', 'new')
        due = it.get('due') or today
        if status == 'new':
            new_count += 1
        elif status == 'mastered':
            mastered_count += 1
        else:
            review_count += 1
        if due <= today:
            due_count += 1
            queue.append(it)
    queue.sort(key=lambda it: (0 if it.get('status') == 'new' else 1, it.get('due') or today, it.get('id') or ''))
    return {
        'date': today,
        'new_count': new_count,
        'review_count': review_count,
        'mastered_count': mastered_count,
        'total': len(items),
        'due_count': due_count,
        'queue': queue,
    }


# ---------------------------------------------------------------------------
# AI 拆解（打散難點：語法＋含義）
# ---------------------------------------------------------------------------

def _parse_breakdown(text):
    """Extract a JSON object from the LLM reply, tolerating markdown fences."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t, flags=re.IGNORECASE | re.MULTILINE)
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r'\{.*\}', t, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def breakdown(original, translation, cfg=None):
    """Ask the configured LLM to split the sentence into grammar points +
    meaning. Returns a dict {grammar, meaning, example, confusion} (all strings),
    or None when no usable reply / no API key."""
    text = (original or '').strip()
    if not text:
        text = (translation or '').strip()
    if not text:
        return None
    if cfg is None and read_config is not None:
        try:
            cfg = (read_config().get('ocr') or {}).get('translate') or {}
        except Exception:
            cfg = {}
    cfg = cfg or {}
    if not cfg.get('api_key') and cfg.get('provider') not in ('ollama',):
        # 沒 key 就乾脆回 None，由呼叫端決定要不要提示
        return None
    try:
        reply = chat([
            {'role': 'system', 'content': BREAKDOWN_SYSTEM_PROMPT},
            {'role': 'user', 'content': f'原文：{original}\n譯文：{translation}'},
        ], cfg)
    except Exception:
        return None
    data = _parse_breakdown(reply)
    if not isinstance(data, dict):
        return None
    grammar = data.get('grammar')
    if isinstance(grammar, list):
        grammar = '\n'.join('- ' + str(g).strip() for g in grammar if str(g).strip())
    elif isinstance(grammar, str):
        grammar = grammar.strip()
    else:
        grammar = ''
    corrected = str(data.get('corrected_original') or '').strip()
    if not corrected:
        corrected = original.strip() if original and original.strip() else ''
    return {
        'corrected_original': corrected,
        'grammar': grammar or '',
        'meaning': str(data.get('meaning') or '').strip(),
        'example': str(data.get('example') or '').strip(),
        'confusion': str(data.get('confusion') or '').strip(),
    }


__all__ = [
    'REVIEW_DIR', 'MASTERED_DAYS', '_STATUS_LABELS',
    'get_items', 'find_item', 'capture_items', 'capture_item', 'update_item', 'delete_item',
    'grade_item', 'set_item_state', 'dashboard', 'breakdown',
]
