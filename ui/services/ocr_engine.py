import io
import json
import math
import os
import re
import tempfile
import threading

from datetime import datetime

from core.comic import get_comic_dir, SCRIPT_DIR

from ui.services.image_variants import Image
from ui.services.translate import translate
from ui.services.markdown_io import export_markdown, extract_translations, format_for_llm

# --- OCR debug logging -------------------------------------------------------
_OCR_LOG_LOCK = threading.Lock()
_SAVE_LOCK = threading.Lock()
_OCR_LOG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '.cache', 'ocr_debug.log')

def _ocr_log(msg):
    """Append a line to the OCR debug log (thread-safe)."""
    try:
        os.makedirs(os.path.dirname(_OCR_LOG_PATH), exist_ok=True)
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with _OCR_LOG_LOCK:
            with open(_OCR_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(f'[{ts}] {msg}\n')
    except Exception:
        pass


def _get_debug_dir(page_name):
    """Return the debug output directory for a given page: <cwd>/_debug/<page_name>/."""
    d = os.path.join(str(SCRIPT_DIR), '_debug', os.path.splitext(page_name)[0])
    os.makedirs(d, exist_ok=True)
    return d

# PaddleOCR 3.x (PaddleX) defaults to oneDNN/MKLDNN on CPU, which crashes on some
# PaddlePaddle 3.x builds ("ConvertPirAttribute2RuntimeAttribute not support").
# Fall back to the plain CPU backend. Must be set before PaddleOCR is imported
# (it is lazy-imported in run_ocr), so this runs at module import time.
os.environ.setdefault('PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT', '0')

VALID_READING_ORDERS = ('auto', 'horizontal', 'vertical')

# Auto-OCR drops recognized lines below this recognition confidence.  Mirrors
# BalloonTranslator's confidence-driven filtering (its DBNet box threshold is
# 0.6); small/blurry noise usually scores low, so this replaces a hard
# min-pixel-size rule as the primary small-text filter.
MIN_REC_SCORE = 0.65


# --- reading-order helpers ---------------------------------------------------
# PaddleOCR reports text-line boxes with pixel coordinates.  Its built-in
# sorting is left-to-right, which is wrong for vertical (竪排 / 縦書き) text:
# Japanese and Traditional Chinese vertical columns read right-to-left, while
# horizontal lines read left-to-right.  We re-derive the reading order from the
# box geometry so the column order follows the writing convention of the text.

def _to_quad(v):
    """Best-effort normalize a detection box to a list of 4 [x, y] points.

    Accepts 4-point polys (list/tuple/ndarray), flat 8-number boxes, and dicts
    with 'x'/'y'.  Returns None if it does not look like a quad.
    """
    if v is None:
        return None
    try:
        if hasattr(v, 'tolist'):
            v = v.tolist()
        if not isinstance(v, (list, tuple)):
            return None
        # flat 8-number box: [x1, y1, x2, y2, x3, y3, x4, y4]
        if len(v) == 8 and all(isinstance(n, (int, float)) for n in v):
            return [[float(v[0]), float(v[1])], [float(v[2]), float(v[3])],
                    [float(v[4]), float(v[5])], [float(v[6]), float(v[7])]]
        if len(v) != 4:
            return None
        pts = []
        for p in v:
            if isinstance(p, dict):
                if 'x' in p and 'y' in p:
                    pts.append([float(p['x']), float(p['y'])])
                    continue
                return None
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                pts.append([float(p[0]), float(p[1])])
            else:
                return None
        if len(pts) == 4:
            return pts
    except Exception:
        pass
    return None


def _score_of(v):
    """Normalize a recognition confidence to a float in [0, 1], or None if unknown."""
    try:
        return min(1.0, max(0.0, float(v)))
    except Exception:
        return None


def _extract_text_items(result):
    """Extract (quad, text, score) triples across PaddleOCR 2.x / 3.x formats.

    ``quad`` is a list of 4 [x, y] points or None when the text has no box.
    ``score`` is the recognition confidence (0..1) or None when unavailable.
    """
    items = []

    def add(quad, text, score=None):
        t = (text or '').strip()
        if t:
            items.append((_to_quad(quad), t, _score_of(score)))

    def rec(node, inherited_quad=None):
        if isinstance(node, str):
            add(inherited_quad, node)
        elif isinstance(node, dict):
            # single text-line record (3.x text_rec_res entries) — text + its poly
            for k in ('rec_text', 'text', 'transcription'):
                v = node.get(k)
                if isinstance(v, str) and v.strip():
                    quad = None
                    for pk in ('rec_polys', 'dt_polys', 'rec_boxes', 'box', 'points'):
                        q = _to_quad(node.get(pk))
                        if q:
                            quad = q
                            break
                    score = node.get('rec_score') or node.get('score') or node.get('confidence')
                    add(quad or inherited_quad, v, score)
            # 3.x per-line records list: text_rec_res is [{'rec_text': ..., 'rec_polys': ...}, ...]
            if isinstance(node.get('text_rec_res'), list):
                for entry in node['text_rec_res']:
                    rec(entry, inherited_quad)
            # batch lists (3.x top-level res: rec_texts + rec_scores + rec_polys / dt_polys)
            if isinstance(node.get('rec_texts'), list):
                polys = node.get('rec_polys') or node.get('dt_polys') or []
                scores = node.get('rec_scores') or []
                for i, t in enumerate(node['rec_texts']):
                    if not isinstance(t, str):
                        continue
                    quad = _to_quad(polys[i]) if i < len(polys) else None
                    score = scores[i] if i < len(scores) else None
                    add(quad, t, score)
            if 'res' in node:
                rec(node['res'], inherited_quad)
        elif isinstance(node, (list, tuple)):
            # 2.x item: [ [quad points...], (text, score) ]
            if (len(node) == 2
                    and isinstance(node[0], (list, tuple))
                    and isinstance(node[1], (list, tuple)) and len(node[1]) >= 1
                    and isinstance(node[1][0], str)):
                score = node[1][1] if len(node[1]) >= 2 else None
                add(node[0], node[1][0], score)
                return
            for item in node:
                rec(item, inherited_quad)
        elif hasattr(node, 'json'):
            try:
                rec(node.json, inherited_quad)
            except Exception:
                pass

    rec(result)

    seen = set()
    out = []
    for quad, t, s in items:
        if t in seen:
            continue
        seen.add(t)
        out.append((quad, t, s))
    return out


def _box_metrics(quad):
    """Bounding-box metrics (axis-aligned) for a 4-point quad."""
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return {'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1,
            'cx': (x0 + x1) / 2.0, 'cy': (y0 + y1) / 2.0,
            'w': x1 - x0, 'h': y1 - y0}


def _is_vertical(quad):
    """判斷四邊形對應的文本方向（竪排/橫排）。

    基於 BalloonTranslator sort_pnts 算法：
    1. 計算四邊形 4 條邊的長度和向量
    2. 取最長的兩條邊，得到主方向向量
    3. 寬度分量 × 1.2 ≤ 高度分量 → 竪排
    4. 正方形框（4 邊長度接近）預設橫排
    """
    pts = [tuple(p) for p in quad]

    # 按角度排序，得到凸包順序（逆時針）
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0

    def _angle(p):
        return math.atan2(p[1] - cy, p[0] - cx)

    sorted_pts = sorted(pts, key=_angle)

    # 計算 4 條邊的長度和向量
    sides = []
    for i in range(4):
        p1 = sorted_pts[i]
        p2 = sorted_pts[(i + 1) % 4]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.hypot(dx, dy)
        sides.append((length, dx, dy))

    # 取最長的兩條邊
    sides.sort(key=lambda x: x[0], reverse=True)
    top2 = sides[:2]

    # 修正方向：確保兩向量不是反向的
    dx1, dy1 = top2[0][1], top2[0][2]
    dx2, dy2 = top2[1][1], top2[1][2]
    if dx1 * dx2 + dy1 * dy2 < 0:
        dx2, dy2 = -dx2, -dy2

    # 主方向向量（取絕對值）
    svx = abs((dx1 + dx2) / 2.0)
    svy = abs((dy1 + dy2) / 2.0)

    # 竪排判定：水平分量 × 1.2 ≤ 垂直分量
    is_vertical = svx * 1.2 <= svy

    # 正方形框（4 邊長度接近）預設橫排
    lengths = sorted([s[0] for s in sides])
    if lengths[0] > 0 and lengths[-1] / lengths[0] < 1.15:
        is_vertical = False

    return is_vertical


def _gap_is_blank(img_gray, a, b, mode, gap_min):
    """Check whether two candidate boxes are separated by a blank structural gap.

    Returns True when the region between the two boxes is a WIDE empty band
    (wider than ``gap_min``, no text pixels), which means they belong to
    DIFFERENT speech bubbles and must NOT be merged. ``img_gray`` is the
    grayscale image array in the same coordinate space as the box metrics.

    - vertical mode: columns side by side → gap band is horizontal
    - horizontal mode: rows stacked → gap band is vertical
    """
    if img_gray is None:
        return False
    h, w = img_gray.shape[:2]
    if mode == 'vertical':
        # horizontal band between the two columns
        gap_x0 = min(a['x1'], b['x1'])
        gap_x1 = max(a['x0'], b['x0'])
        gap_w = gap_x1 - gap_x0
        y0 = max(a['y0'], b['y0'])
        y1 = min(a['y1'], b['y1'])
        band = (int(y0), int(y1), int(gap_x0), int(gap_x1))
    else:
        # vertical band between the two rows
        gap_y0 = min(a['y1'], b['y1'])
        gap_y1 = max(a['y0'], b['y0'])
        gap_w = gap_y1 - gap_y0
        x0 = max(a['x0'], b['x0'])
        x1 = min(a['x1'], b['x1'])
        band = (int(gap_y0), int(gap_y1), int(x0), int(x1))
    y0, y1, x0, x1 = band
    if y1 <= y0 or x1 <= x0:
        return False  # boxes touch/overlap → not a gap
    if x1 > w or y1 > h or x0 < 0 or y0 < 0:
        return False
    if gap_w < gap_min:
        return False  # narrow gap → same balloon's column/row spacing, merge
    region = img_gray[y0:y1, x0:x1]
    if region.size == 0:
        return False
    ink = float((region < 128).sum()) / region.size
    # a blank gap: no text pixels AND the band is wide enough to be structural
    return ink < 0.05


def _merge_blocks(selected, mode, W, H, img_gray=None):
    """合併相鄰的檢測框為文字塊（一個對話氣泡內的多行/多列）。

    採兩遍合併：

    - 第一遍（嚴格）：竪排只併「同一列堆疊」的框——兩框中心距離 < threshold、
      x 有實質重疊（重疊 > 較小框寬 30%）且垂直範圍重疊。這樣做能避免把
      「靠在一起但各自獨立」的氣泡誤併（例：025C 的「シスター」與
      「エレーヌー」）。x 重疊比例很小（>0 但 ≤ 較小框寬 30%）或左右錯開
      （重疊 ≤ 0）的相鄰列一律留到第二遍，避免貪心順序把中間列孤立
      （例：002 底部的「なんか／恐そうな人／だなぁ」）。
      橫排維持原規則（垂直中心距離 + 水平重疊 + 對齊）。

    - 第二遍（放寬，竪排）：只合併「讀序相鄰」的文字塊——兩塊之間沒有其他
      塊。因為中間沒有別的氣泡，可以放心把第一遍因保守而拆開的同氣泡列補併
      （例：002 的「てか…」與其左側欄、底部「なんか／恐そうな人／だなぁ」），
      同時不會把「シスター」與「エレーヌー」這種中間夾著別的文字塊的獨立
      氣泡併在一起。
      竪排條件：中心距離 < threshold 且兩塊都是直排形態，且（垂直範圍重疊、
      x 重疊比例 ≤ 較小塊寬 30%）或（左右錯開、頂端大致對齊）。

    另外，若兩個框/塊之間有一條寬且空白的結構性間隙（見 _gap_is_blank），
    判定為兩個不同的對話氣泡，即使距離/重疊符合也不合併。

    回傳合併後的 [(metrics, text, quad), ...]，其中：
    - metrics 為合併後的外接矩形 bbox
    - text 為按閱讀順序拼接的文本（換行分隔）
    - quad 保留第一個原始框（用於方向判定，避免外接矩形誤判）
    """
    threshold = max(W, H) * 0.05    # 合併距離（中心距離 / 重疊）
    gap_min = max(W, H) * 0.02     # 結構性空白間隙的最小寬度（低於此視為同氣泡的行/列間距）
    blocks = []  # 每個 block: {'metrics': m, 'texts': [..], 'quad': q}

    def _grow(blk, m, text):
        """把一個框併入 block：合併 bbox 並加入文本（避免重複）。"""
        if text and text not in blk['texts']:
            # 子字串去重：若新文本是已有文本的子集（或反之），跳過
            is_dup = False
            for existing in blk['texts']:
                if len(text) >= 4 and text in existing:
                    is_dup = True
                    break
                if len(existing) >= 4 and existing in text:
                    # 新文本包含已有文本 → 替換
                    blk['texts'] = [t for t in blk['texts'] if t != existing]
                    break
            if not is_dup:
                blk['texts'].append(text)
        bm = blk['metrics']
        bm['x0'] = min(m['x0'], bm['x0'])
        bm['y0'] = min(m['y0'], bm['y0'])
        bm['x1'] = max(m['x1'], bm['x1'])
        bm['y1'] = max(m['y1'], bm['y1'])
        bm['cx'] = (bm['x0'] + bm['x1']) / 2.0
        bm['cy'] = (bm['y0'] + bm['y1']) / 2.0
        bm['w'] = bm['x1'] - bm['x0']
        bm['h'] = bm['y1'] - bm['y0']

    def _absorb(dst, src):
        """把 src block 整個併入 dst block（第二遍合併塊）。"""
        for t in src['texts']:
            if t not in dst['texts']:
                dst['texts'].append(t)
        _grow(dst, src['metrics'], None)

    # --- 第一遍：嚴格合併（只併「同一列堆疊」的框）---
    # 左右錯開的相鄰列（x 不重疊或重疊比例很小）一律留到第二遍處理：若
    # 第一遍就併，貪心順序會把中間列孤立（例：002 底部的「なんか／恐そう
    # な人／だなぁ」，先併外側兩列就輪不到中間列）。
    for m, text, quad in selected:
        merged = False
        for blk in blocks:
            bm = blk['metrics']
            if mode == 'vertical':
                dist = abs(m['cx'] - bm['cx'])
                if dist >= threshold:
                    continue
                v_overlap = min(m['y1'], bm['y1']) - max(m['y0'], bm['y0'])
                x_ov = min(m['x1'], bm['x1']) - max(m['x0'], bm['x0'])
                # 同列堆疊：x 重疊比例足夠才視為同一列，避免把靠在一起
                # 的獨立氣泡（「シスター」/「エレーヌー」）誤併
                if not (x_ov > 0 and v_overlap > 0
                        and x_ov > min(m['w'], bm['w']) * 0.3):
                    continue
                if _gap_is_blank(img_gray, m, bm, 'vertical', gap_min):
                    continue  # blank column gap → separate balloons
                merged = True
            else:
                # 橫排：垂直中心距離 + 水平重疊
                dist = abs(m['cy'] - bm['cy'])
                h_overlap = min(m['x1'], bm['x1']) - max(m['x0'], bm['x0'])
                if dist < threshold and h_overlap > 0:
                    # 對角靠近的不同塊：左邊界（左對齊）與水平中心（居中）都明顯
                    # 不齊 → 不同對話氣泡。任一對齊即視為同塊的多行。
                    if (abs(m['x0'] - bm['x0']) > threshold
                            and abs(m['cx'] - bm['cx']) > threshold):
                        continue
                    if _gap_is_blank(img_gray, m, bm, 'horizontal', gap_min):
                        continue  # blank row gap → separate balloons
                    merged = True
                else:
                    continue
            if merged:
                _grow(blk, m, text)
                break
        if not merged:
            blocks.append({'metrics': dict(m), 'texts': [text], 'quad': quad})

    # --- 第二遍：只合併讀序相鄰的文字塊，放寬條件補回被拆開的同氣泡列 ---
    if mode == 'vertical':
        changed = True
        while changed:
            changed = False
            i = 1
            while i < len(blocks):
                a = blocks[i - 1]['metrics']
                b = blocks[i]['metrics']
                merge = False
                if abs(a['cx'] - b['cx']) < threshold:
                    v_overlap = min(a['y1'], b['y1']) - max(a['y0'], b['y0'])
                    x_ov = min(a['x1'], b['x1']) - max(a['x0'], b['x0'])
                    if v_overlap > 0:
                        # 只補併「x 重疊比例很小或錯開」的相鄰直排列（第一遍因
                        # 保守而拆開者，如 002 的「てか…」與其左側欄）。x 重疊
                        # 比例大代表上下堆疊在同一 x 帶，是不同氣泡，不併
                        # （例：025B 的「シスター」塊與其下方的「1/0/日」塊）；
                        # 非直排形態（橫排小框，如 002 的「0」「o」）也不併，
                        # 避免把氣泡旁的獨立小元素吞進長欄塊。
                        min_w = min(a['w'], b['w'])
                        merge = (x_ov <= min_w * 0.3
                                 and a['h'] > a['w'] and b['h'] > b['w'])
                    elif x_ov <= 0 and a['h'] > a['w'] and b['h'] > b['w']:
                        # 左右錯開、頂端大致對齊的相鄰列
                        y_gap = max(a['y0'], b['y0']) - min(a['y1'], b['y1'])
                        merge = y_gap < gap_min
                if merge and not _gap_is_blank(img_gray, a, b, 'vertical', gap_min):
                    _absorb(blocks[i - 1], blocks[i])
                    del blocks[i]
                    changed = True
                    # 不遞增 i：併大的塊繼續與下一個相鄰塊比較
                else:
                    i += 1

    out = []
    for blk in blocks:
        bm = blk['metrics']
        merged_text = '\n'.join(blk['texts'])
        out.append((bm, merged_text, blk['quad']))
    return out


def _overlap_ratio(a0, a1, b0, b1):
    """Overlap of two 1-D intervals, as a ratio of the larger interval.

    Using the larger span keeps heterogeneous boxes apart: a tall vertical
    column only touching a short horizontal line would otherwise read as the
    same row (small-overlap / small-span rounds up to ~1.0).
    """
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    span = max(a1 - a0, b1 - b0)
    return inter / span if span > 0 else 0.0


def _order_vertical(infos):
    """Vertical layout, read in horizontal bands (top → bottom).

    漫畫豎排頁常分為多個水平「段」（上下分鏡），閱讀時先讀最上方的一段，
    段內再按列右→左、列內上→下。若整頁只是一段（欄位連續到底），結果與
    原本的「整頁列右→左」相同。

    Returns the info dicts in reading order."""
    if not infos:
        return []
    hs = sorted(max(1.0, m['y1'] - m['y0']) for m in infos)
    med_h = hs[len(hs) // 2]

    # 1. 按垂直中心聚類成水平段：段間間隙 > 1.2 字高 → 分開
    bands = []
    for m in sorted(infos, key=lambda m: m['cy']):
        placed = False
        for band in bands:
            if m['cy'] - band['cy'] < med_h * 1.2:
                band['items'].append(m)
                band['cy'] = sum(mm['cy'] for mm in band['items']) / len(band['items'])
                placed = True
                break
        if not placed:
            bands.append({'cy': m['cy'], 'items': [m]})

    # 2. 段間上→下；段內列右→左、列內上→下
    out = []
    for band in sorted(bands, key=lambda b: b['cy']):
        columns = []
        for m in sorted(band['items'], key=lambda m: m['cx'], reverse=True):
            placed = False
            for col in columns:
                if _overlap_ratio(m['x0'], m['x1'], col['x0'], col['x1']) > 0.3:
                    col['items'].append(m)
                    col['x0'] = min(col['x0'], m['x0'])
                    col['x1'] = max(col['x1'], m['x1'])
                    placed = True
                    break
            if not placed:
                columns.append({'x0': m['x0'], 'x1': m['x1'], 'items': [m]})
        for col in columns:  # columns created rightmost-first -> R->L
            for m in sorted(col['items'], key=lambda m: m['cy']):
                out.append(m)
    return out


def _order_horizontal(infos):
    """Horizontal layout: rows read top -> bottom, left -> right inside a row.
    Returns the info dicts in reading order."""
    rows = []
    for m in sorted(infos, key=lambda m: m['cy']):
        placed = False
        for row in rows:
            if _overlap_ratio(m['y0'], m['y1'], row['y0'], row['y1']) > 0.3:
                row['items'].append(m)
                row['y0'] = min(row['y0'], m['y0'])
                row['y1'] = max(row['y1'], m['y1'])
                placed = True
                break
        if not placed:
            rows.append({'y0': m['y0'], 'y1': m['y1'], 'items': [m]})
    out = []
    for row in rows:  # rows created topmost-first, so iteration is top -> bottom
        for m in sorted(row['items'], key=lambda m: m['cx']):
            out.append(m)
    return out


def _item_score(item):
    """Recognition score of an item (triple) or None (2-tuple / unknown)."""
    return _score_of(item[2]) if len(item) > 2 else None


def _ordered_items(items, mode='auto'):
    """(quad, text, score) in reading order, plus the resolved layout mode.

    Items may be (quad, text) or (quad, text, score).  Unlike
    _sort_in_reading_order, the quads are kept so callers can place markers at
    each detected box (used by auto OCR).
    """
    mode = mode if mode in VALID_READING_ORDERS else 'auto'

    positioned = [it for it in items if it[0]]
    floating = [it for it in items if not it[0]]  # texts without a box go last, in order
    if not positioned:
        return [(None, it[1], _item_score(it)) for it in floating], \
            ('vertical' if mode == 'vertical' else 'horizontal')

    infos = []
    for it in positioned:
        q, t = it[0], it[1]
        m = _box_metrics(q)
        m['quad'] = q
        m['text'] = t
        m['score'] = _item_score(it)
        # 用四邊形幾何判定方向（BalloonTranslator 的 sort_pnts 邏輯）：
        # 主方向向量之水平分量 × 1.2 ≤ 垂直分量 → 竪排；正方形框預設橫排。
        m['vertical'] = _is_vertical(q)
        infos.append(m)

    if mode == 'auto':
        # 統計竪排框數量，簡單多數決（超過一半才認定為竪排）。
        # 方形框（長寬比接近 1）無方向資訊，不參與統計——豎排頁面常見的
        # 單字框就是方形，若計入會把竪排比例拉低而誤判為橫排。
        vert = 0
        total = 0
        for m in infos:
            w, h = m['w'], m['h']
            if h > w * 1.15:
                vert += 1
                total += 1
            elif w > h * 1.15:
                total += 1
            # else: 方形框，跳過
        mode = 'vertical' if total > 0 and vert > total / 2 else 'horizontal'

    ordered = _order_vertical(infos) if mode == 'vertical' else _order_horizontal(infos)
    out = [(m['quad'], m['text'], m['score']) for m in ordered] \
        + [(None, it[1], _item_score(it)) for it in floating]
    return out, mode


def _order_by_panels(items, img_rgb, reading_order):
    """依漫畫分鏡格排序：格間照分鏡閱讀順序，格內照文字方向。

    漫畫閱讀順序由分鏡格（panel）決定（右→左、上→下），與文字橫豎無關。
    偵測分鏡格後，每個文字框歸屬其格，逐格用 `_ordered_items`（方向排序）
    排格內文字。分鏡格少於 2 或偵測失敗時回傳 None（呼叫端改用 `_ordered_items`）。
    """
    try:
        from PIL import Image
        from ui.services import panel_finder
    except Exception:
        return None
    try:
        panels = panel_finder.calc_panel_bboxes_xyxy(Image.fromarray(img_rgb))
        if len(panels) < 2:
            return None
        groups = {i: [] for i in range(len(panels))}
        for it in items:
            quad = it[0]
            if not quad:
                return None
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            cx = (min(xs) + max(xs)) / 2
            cy = (min(ys) + max(ys)) / 2
            best = None
            for i, p in enumerate(panels):
                if p[0] <= cx <= p[2] and p[1] <= cy <= p[3]:
                    best = i
                    break
            if best is None:
                return None
            groups[best].append(it)
        out = []
        for i in range(len(panels)):  # panels 已按分鏡閱讀順序
            if not groups[i]:
                continue
            ordered, _ = _ordered_items(groups[i], reading_order)
            out.extend(ordered)
        if len(out) != len(items):
            return None
        return out
    except Exception:
        return None


def _sort_in_reading_order(items, mode='auto'):
    """Re-order (quad, text) pairs into the writing convention of the text.

    ``mode``: 'auto' judges from the boxes (majority of tall boxes => vertical
    layout => right-to-left columns); 'vertical' / 'horizontal' force a layout.

    Returns ``(lines, resolved_mode)`` where ``resolved_mode`` is the layout
    actually applied ('vertical' or 'horizontal'), so callers can react to the
    text orientation (e.g. where to place a label marker).
    """
    ordered, mode = _ordered_items(items, mode)
    return [it[1] for it in ordered], mode


def _extract_texts(result):
    """Best-effort extraction of recognized text lines across PaddleOCR 2.x / 3.x formats."""
    texts = []

    def rec(node):
        if isinstance(node, str):
            texts.append(node)
        elif isinstance(node, dict):
            for k in ('rec_text', 'text', 'transcription'):
                v = node.get(k)
                if isinstance(v, str) and v.strip():
                    texts.append(v)
            if isinstance(node.get('rec_texts'), list):
                for t in node['rec_texts']:
                    if isinstance(t, str) and t.strip():
                        texts.append(t)
            if 'res' in node:
                rec(node['res'])
        elif isinstance(node, (list, tuple)):
            for item in node:
                rec(item)
        elif hasattr(node, 'json'):
            try:
                rec(node.json)
            except Exception:
                pass

    rec(result)

    seen = set()
    out = []
    for t in texts:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _make_ocr(PaddleOCR, lang):
    """Construct PaddleOCR across 2.x / 3.x, whose constructor args differ.

    For 3.x we disable `use_doc_orientation_classify` (whole-page rotation).  Its
    default True makes the doc-orientation classifier rotate tall manga pages 90°,
    which shifts every bbox into a swapped coordinate space and breaks marker
    placement.  `use_textline_orientation` stays True so vertical-text lines are
    still recognized correctly (this is the "cls" behavior we need for 竪排).
    """
    attempts = (
        # 3.x: 禁用整页旋转分类，保留文本行方向识别
        {'lang': lang, 'use_doc_orientation_classify': False,
         'use_textline_orientation': True},
        {'lang': lang, 'use_doc_orientation_classify': False},
        {'lang': lang},                                        # 3.x minimal
        {'lang': lang, 'use_angle_cls': True},                 # 2.x
        {'lang': lang, 'show_log': False},                     # 2.x alt
        {'lang': lang, 'use_angle_cls': True, 'show_log': False},
    )
    last = None
    for kwargs in attempts:
        try:
            return PaddleOCR(**kwargs)
        except Exception as e:  # unknown-argument errors are cheap (pre-model)
            last = e
    raise last


def _run_ocr(ocr, img_path, use_cls=True):
    """Call PaddleOCR across 2.x (ocr) and 3.x (predict) with path input.

    ``use_cls`` toggles PaddleOCR's angle classifier.  It is ON by default:
    the cls model rotates vertical (竪排) text pages 90° before detection, which
    is how PaddleOCR correctly recognizes vertical text.  The side effect — bbox
    coordinates landing in a swapped (rotated) space — is undone by the rotation
    detection in `_iter_page_events`, not by disabling cls here.
    """
    for method in ('ocr', 'predict'):
        if not hasattr(ocr, method):
            continue
        fn = getattr(ocr, method)
        attempts = ({'cls': use_cls}, {}) if use_cls else ({}, {'cls': True})
        for kwargs in attempts:
            try:
                r = fn(img_path, **kwargs)
                if r is not None:
                    return r
            except TypeError:
                # some versions reject cls kwarg
                continue
            except Exception:
                continue
    raise RuntimeError('PaddleOCR 無法執行（請確認版本與模型）')


# --- cached OCR instance (model load is slow; keep it warm across requests) ---
_ocr_lock = threading.Lock()
_ocr_instances = {}   # lang -> PaddleOCR instance
_ocr_state = {'status': 'idle', 'lang': None, 'error': None}  # idle|loading|ready|error


def _ensure_ocr(lang):
    """Get (or lazily build) the cached PaddleOCR instance for `lang`. Blocking."""
    with _ocr_lock:
        ocr = _ocr_instances.get(lang)
        if ocr is not None:
            return ocr
        try:
            from paddleocr import PaddleOCR
        except Exception:
            raise RuntimeError('未安裝 paddleocr，請執行 pip install paddleocr paddlepaddle')
        ocr = _make_ocr(PaddleOCR, lang)
        _ocr_instances[lang] = ocr
        _ocr_state.update(status='ready', lang=lang, error=None)
        return ocr


def ocr_status():
    with _ocr_lock:
        return dict(_ocr_state)


def preload_ocr(lang):
    """Start a background load of the OCR model. Returns the current state dict."""
    with _ocr_lock:
        if _ocr_instances.get(lang) is not None:
            _ocr_state.update(status='ready', lang=lang, error=None)
            return dict(_ocr_state)
        if _ocr_state.get('status') == 'loading':
            return dict(_ocr_state)
        _ocr_state.update(status='loading', lang=lang, error=None)
        snapshot = dict(_ocr_state)  # 'loading' — return immediately, don't block on load

    def _work():
        try:
            _ensure_ocr(lang)
        except Exception as e:
            with _ocr_lock:
                _ocr_state.update(status='error', lang=lang, error=str(e))

    threading.Thread(target=_work, daemon=True).start()
    return snapshot


def unload_ocr(lang=None):
    """Drop cached OCR instance(s), freeing memory. Returns the new state dict."""
    with _ocr_lock:
        if lang is None:
            _ocr_instances.clear()
        else:
            _ocr_instances.pop(lang, None)
        _ocr_state.update(status='idle', lang=None, error=None)
        return dict(_ocr_state)


def run_ocr(img_name, box, lang='japan', reading_order='auto'):
    """Crop `box` (normalized x,y,w,h) from the image and OCR it.

    ``reading_order`` controls how recognized lines are ordered: 'auto' judges
    from the boxes (vertical / 竪排 text => columns right-to-left, horizontal
    text => left-to-right), 'vertical' and 'horizontal' force a direction.

    Returns ``(text, layout)`` where ``layout`` is the detected/forced
    orientation ('horizontal' or 'vertical').
    """
    if Image is None:
        raise RuntimeError('Pillow 未安裝，無法裁切圖片')

    orig_path = os.path.join(get_comic_dir(), img_name)
    if not os.path.exists(orig_path):
        raise FileNotFoundError(f'Image not found: {orig_path}')

    _ocr_log(f'[BoxOCR] img={img_name} box={box}')

    # crop region - apply EXIF transpose first so coords match browser visual
    from PIL import ImageOps
    try:
        with Image.open(orig_path) as im:
            try:
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass
            W, H = im.size
            x = max(0.0, min(1.0, float(box.get('x', 0))))
            y = max(0.0, min(1.0, float(box.get('y', 0))))
            w = max(0.0, min(1.0 - x, float(box.get('w', 0))))
            h = max(0.0, min(1.0 - y, float(box.get('h', 0))))
            left, top = int(x * W), int(y * H)
            right, bottom = int((x + w) * W), int((y + h) * H)
            if right - left < 4 or bottom - top < 4:
                raise RuntimeError('框選範圍太小')
            crop = im.crop((left, top, right, bottom))
            _ocr_log(f'[BoxOCR] crop={crop.width}x{crop.height} pixels (visual size={W}x{H})')
            if crop.width < 40 or crop.height < 40:
                s = 2
                crop = crop.resize((crop.width * s, crop.height * s), Image.LANCZOS)
                _ocr_log(f'[BoxOCR] upscaled to {crop.width}x{crop.height}')
            buf = io.BytesIO()
            crop.save(buf, format='PNG')
            crop_bytes = buf.getvalue()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f'裁切失敗: {e}')

    # write crop to a temp file for PaddleOCR
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    try:
        tmp.write(crop_bytes)
        tmp.close()

        try:
            ocr = _ensure_ocr(lang)
            result = _run_ocr(ocr, tmp.name)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f'OCR 失敗: {e}')
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    # order the recognized lines by the text's writing convention (vertical =>
    # right-to-left columns, horizontal => left-to-right), falling back to the
    # plain text extraction when the box layout cannot be parsed.
    try:
        items = _extract_text_items(result)
        _ocr_log(f'[BoxOCR] detected {len(items)} items')
        if items:
            lines, layout = _sort_in_reading_order(items, reading_order)
            _ocr_log(f'[BoxOCR] layout={layout} lines={len(lines)}')
        else:
            lines, layout = [], 'horizontal'
    except Exception:
        lines, layout = _extract_texts(result), 'horizontal'
        _ocr_log(f'[BoxOCR] fallback extraction lines={len(lines)}')
    if not lines:
        _ocr_log(f'[BoxOCR] ERROR: no text recognized')
        raise RuntimeError('OCR 沒有辨識到文字')
    _ocr_log(f'[BoxOCR] result={repr(chr(10).join(lines))[:200]}')
    return '\n'.join(lines), layout


# --- auto OCR: detect the whole page, label, and translate --------------------
def _ndjson(obj):
    """Serialize an event dict to a newline-terminated NDJSON line (str)."""
    return json.dumps(obj, ensure_ascii=False) + '\n'


def assign_contextual_translations(original_lines, translated_text):
    """Map one batch translation back to each OCR line while preserving order.

    The full-page auto-OCR flow translates all recognized text together so the
    model can use cross-line context. This helper then aligns the output back to
    the original per-line sequence.
    """
    lines = [str(x).strip() for x in (original_lines or []) if str(x).strip()]
    if not lines:
        return []

    text = (translated_text or '').replace('\r\n', '\n').replace('\r', '\n')
    candidates = [ln.strip() for ln in text.split('\n') if ln.strip()]
    if not candidates:
        return [''] * len(lines)

    noise_tokens = (
        '總結', '結果', '答案', '翻譯', '译文', 'translation', 'translated', 'output',
        'summary', '說明', '補充', '注意', '提示', '額外', 'note', 'result', 'response'
    )

    def normalize_candidate(ln):
        ln = re.sub(r'^(?:翻譯|译文|translation|translated|result|output|summary|答案|結果|總結)\s*[:：]?\s*', '', ln, flags=re.I)
        ln = re.sub(r'^[\-•*\d.\s]+', '', ln)
        return ln.strip()

    cleaned = []
    for ln in candidates:
        s = normalize_candidate(ln)
        if not s:
            continue
        if any(tok in s for tok in noise_tokens):
            continue
        cleaned.append(s)

    # Most model outputs follow one translated line per OCR line; keep that order.
    if len(cleaned) == len(lines):
        return cleaned

    # If the model emits a single paragraph or includes extra commentary, trim to
    # the expected number of lines and drop the non-translation tails.
    if len(cleaned) > len(lines):
        return cleaned[:len(lines)]

    # If the model emits a single paragraph, split it back into lines conservatively.
    single = '\n'.join(cleaned) if cleaned else text
    split = [normalize_candidate(ln) for ln in single.split('\n') if normalize_candidate(ln)]
    if len(split) >= len(lines):
        return split[:len(lines)]

    # Final fallback: preserve ordering and leave missing lines blank.
    out = []
    for idx in range(len(lines)):
        if idx < len(split):
            out.append(split[idx])
        else:
            out.append('')
    return out


def _detect_ctd_items(orig_path, lang, debug_dir=None):
    """用 CTD 檢測 + PaddleOCR 識別整頁。回傳 (items, W, H, img_rgb, raw_blocks) 或 None。

    CTD（Comic Text Detector）是漫畫專用檢測器，檢測框遠比 PaddleOCR 準
    （誤差 <0.5%），且直接回傳「原圖視覺空間」座標（無需縮放/旋轉修正）。
    ``items`` 為 [(quad, text, score), ...]，quad 為 4 點原圖座標。
    失敗（CTD 模型缺失、偵測不到文字等）回傳 None，由呼叫端退回 PaddleOCR。

    ``debug_dir``：若提供，在該目錄保存 CTD 框線視覺化圖片。
    """
    import numpy as _np
    import cv2 as _cv2
    from PIL import ImageOps
    try:
        from ui.services import ctd_engine
    except Exception as e:
        _ocr_log(f'[CTD] import 失敗: {e}')
        return None
    try:
        with Image.open(orig_path) as im:
            im = ImageOps.exif_transpose(im)
            W, H = im.size
            img_rgb = _np.asarray(im.convert('RGB'))
        img_bgr = _cv2.cvtColor(img_rgb, _cv2.COLOR_RGB2BGR)
        blocks = ctd_engine.detect_blocks(img_bgr)
        if not blocks:
            _ocr_log('[CTD] 未偵測到文字框')
            return None
        ocr = _ensure_ocr(lang)
        ctd_engine.recognize_blocks(ocr, img_bgr, blocks,
                                    save_crops_dir=debug_dir)
        items = []
        empty_count = 0
        for blk in blocks:
            text = (blk.get('text') or '').strip()
            if text:
                items.append((blk['quad'], text, blk.get('score')))
            else:
                empty_count += 1
        if empty_count:
            _ocr_log(f'[CTD] {empty_count} 個框 OCR 結果為空，已刪除')
        if not items:
            _ocr_log('[CTD] 偵測到框但無文字')
            return None
        # Debug: draw CTD boxes on original image
        if debug_dir:
            try:
                vis = img_rgb.copy()
                for blk in blocks:
                    quad = blk['quad']
                    pts = _np.array(quad, dtype=_np.int32)
                    _cv2.polylines(vis, [pts], isClosed=True, color=(255, 0, 0), thickness=3)
                    text = (blk.get('text') or '')[:20]
                    if text:
                        x0, y0 = int(min(p[0] for p in quad)), int(min(p[1] for p in quad))
                        _cv2.putText(vis, text, (x0, max(y0 - 5, 15)),
                                     _cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                vis_path = os.path.join(debug_dir, 'ctd_boxes.png')
                Image.fromarray(vis).save(vis_path, format='PNG')
                _ocr_log(f'[Debug] CTD boxes saved to {vis_path}')
            except Exception as e:
                _ocr_log(f'[Debug] Failed to save CTD boxes: {e}')
        return items, W, H, img_rgb, blocks
    except Exception as e:
        _ocr_log(f'[CTD] 偵測失敗: {e}')
        return None


def _iter_page_events(img_name, lang='japan', reading_order='auto', translate_cfg=None,
                      debug=False, detect_only=False):
    """Yield event DICTS for auto-OCR of a single page (no serialization).

    Leaf generator: emits plain dicts so the orchestrators below can decorate
    them with page context before turning them into NDJSON strings.

    Events:
      {"type":"start","total":N}
      {"type":"progress","done":i,"total":N}
      {"type":"done","markers":[...],"translated_ok":k,"translated_fail":f}
      {"type":"error","error":"..."}   (terminal; generator stops)

    ``debug``: 若 True，在 _debug/<page>/ 輸出 CTD 框線圖、裁切圖、markdown。
    ``detect_only``: 若 True，跳過翻譯，markers 的 text 為空（供平行翻譯用）。
    """
    tmp_path = None
    debug_dir = _get_debug_dir(img_name) if debug else None
    try:
        if Image is None:
            raise RuntimeError('Pillow 未安裝，無法讀取圖片')
        orig_path = os.path.join(get_comic_dir(), img_name)
        if not os.path.exists(orig_path):
            raise FileNotFoundError(f'Image not found: {orig_path}')

        # --- 檢測：CTD（漫畫專用、座標精準，回傳原圖視覺座標）---
        ctd_result = _detect_ctd_items(orig_path, lang, debug_dir=debug_dir)
        if ctd_result is None:
            # 圖片可能本來就沒有文字（空白頁），不要中斷：空結果繼續下一頁
            _ocr_log(f'========== page={img_name} CTD 無文字，跳過 ==========')
            yield {'type': 'done', 'markers': [], 'translated_ok': 0, 'translated_fail': 0}
            return
        items, W, H, img_rgb, _raw_blocks = ctd_result
        _ocr_log(f'========== START page={img_name} visual_size={W}x{H} detector=CTD ==========')

        if not items:
            _ocr_log(f'[ERROR] OCR 沒有辨識到文字')
            raise RuntimeError('OCR 沒有辨識到文字')

        _ocr_log(f'[Raw Detected] {len(items)} boxes (detector=CTD)')

        for idx, it in enumerate(items, 1):
            q = it[0]
            s = it[2] if len(it) > 2 else None
            if q:
                m = _box_metrics(q)
                _ocr_log(f'  #{idx} bbox=({m["x0"]:.1f},{m["y0"]:.1f})-({m["x1"]:.1f},{m["y1"]:.1f}) size={m["w"]:.1f}x{m["h"]:.1f} score={s} text={repr(it[1])}')
            else:
                _ocr_log(f'  #{idx} [no quad] text={repr(it[1])}')

        # 排序：優先依漫畫分鏡格（panel）閱讀順序（與文字橫豎無關），
        # 格內再照文字方向；分鏡偵測失敗則退回純方向排序。
        _mode_from_ordered, _mode = _ordered_items(items, reading_order)
        ordered = _order_by_panels(items, img_rgb, reading_order)
        if ordered is None:
            ordered = _mode_from_ordered
        _ocr_log(f'[Reading Order] resolved_mode={_mode}')

        # Filter.  Confidence is the primary small-text filter (low recognition
        # score => drop), like BalloonTranslator.  Size thresholds are only a
        # wide safety net: genuinely tiny specks and whole-page misdetections.
        long_side = max(W, H)
        min_major = max(10.0, long_side * 0.005)
        min_minor = max(4.0, long_side * 0.002)
        _ocr_log(f'[Filter Thresholds] min_major={min_major:.1f} min_minor={min_minor:.1f} min_score={MIN_REC_SCORE}')

        selected = []
        for it in ordered:
            quad, text = it[0], it[1]
            score = it[2] if len(it) > 2 else None
            if not quad:
                _ocr_log(f'[DROP] text={repr(text)[:30]} reason=no_quad')
                continue  # text without a box can't become a marker
            m = _box_metrics(quad)
            if m['w'] * m['h'] > 0.8 * W * H:
                _ocr_log(f'[DROP] text={repr(text)[:30]} bbox=({m["x0"]:.0f},{m["y0"]:.0f},{m["w"]:.0f},{m["h"]:.0f}) reason=too_large ({m["w"]*m["h"]:.0f}px > {0.8*W*H:.0f}px)')
                continue  # detection error covering nearly the whole page
            if max(m['w'], m['h']) < min_major or min(m['w'], m['h']) < min_minor:
                _ocr_log(f'[DROP] text={repr(text)[:30]} bbox=({m["x0"]:.0f},{m["y0"]:.0f},{m["w"]:.0f},{m["h"]:.0f}) reason=too_small (major={max(m["w"],m["h"]):.0f}<{min_major:.0f} or minor={min(m["w"],m["h"]):.0f}<{min_minor:.0f})')
                continue
            if score is not None and score < MIN_REC_SCORE:
                _ocr_log(f'[DROP] text={repr(text)[:30]} score={score:.3f} reason=low_score (<{MIN_REC_SCORE})')
                continue  # low recognition confidence
            _ocr_log(f'[KEEP] text={repr(text)[:30]} bbox=({m["x0"]:.0f},{m["y0"]:.0f},{m["w"]:.0f},{m["h"]:.0f}) score={score}')
            selected.append((m, text, quad))

        _ocr_log(f'[After Filter] {len(selected)}/{len(items)} boxes kept')

        # 合併相鄰框為文字塊（同一對話氣泡內的多行/多列）
        # 提供原圖灰階陣列，用於「結構性空白間隙」檢測，避免把兩個不同的
        # 對話氣泡錯誤合併成一個（見 _gap_is_blank）。
        img_gray = None
        if Image is not None:
            try:
                import numpy as np
                from PIL import ImageOps
                with Image.open(orig_path) as _im:
                    _im = ImageOps.exif_transpose(_im)  # match visual coordinate space
                    img_gray = np.asarray(_im.convert('L'))
            except Exception:
                img_gray = None
        before_merge = len(selected)
        selected = _merge_blocks(selected, _mode, W, H, img_gray)
        _ocr_log(f'[After Merge] {len(selected)}/{before_merge} blocks (merged {before_merge - len(selected)} adjacent boxes)')
        for idx, (m, text, quad) in enumerate(selected, 1):
            _ocr_log(f'  Block #{idx}: bbox=({m["x0"]:.0f},{m["y0"]:.0f},{m["w"]:.0f},{m["h"]:.0f}) vertical={_is_vertical(quad)} text={repr(text)[:60]}')

        if not selected:
            _ocr_log(f'[ERROR] 過濾後沒有可標號的文字')
            raise RuntimeError('過濾後沒有可標號的文字')

        yield {'type': 'start', 'total': len(selected)}
        markers = []
        trans_ok = 0
        trans_fail = 0
        translate_succeeded = False

        original_texts = [text for _, text, _ in selected]
        translated_lines = ['',] * len(original_texts)
        if detect_only:
            _ocr_log('[Translate] skipped (detect_only mode)')
        elif translate_cfg:
            _ocr_log(f'[Translate] batch_length={len(original_texts)} lines')
            try:
                # 使用 markdown 格式进行翻译，确保原文和译文对应
                originals_dict = {i+1: text for i, text in enumerate(original_texts)}
                md_content = export_markdown(originals_dict, page_name=img_name)
                system_prompt = format_for_llm(md_content)

                # Debug: save input markdown
                if debug_dir:
                    try:
                        with open(os.path.join(debug_dir, 'input.md'), 'w', encoding='utf-8') as f:
                            f.write(md_content)
                        _ocr_log(f'[Debug] input.md saved')
                    except Exception:
                        pass
                
                # 调用翻译 API
                from ui.services.translate import chat
                translated_md = chat([
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': md_content},
                ], translate_cfg, timeout=30)

                # Debug: save output markdown
                if debug_dir:
                    try:
                        with open(os.path.join(debug_dir, 'output.md'), 'w', encoding='utf-8') as f:
                            f.write(translated_md)
                        _ocr_log(f'[Debug] output.md saved')
                    except Exception:
                        pass
                
                # 解析返回的 markdown 格式译文
                translations = extract_translations(translated_md)
                if translations:
                    # 按编号顺序提取译文
                    translated_lines = [translations.get(i+1, '') for i in range(len(original_texts))]
                else:
                    # 如果解析失败，回退到旧的翻译方式
                    _ocr_log('[Translate] markdown parse failed, falling back to legacy method')
                    translated = translate('\n'.join(original_texts), translate_cfg)
                    translated_lines = assign_contextual_translations(original_texts, translated)
                
                trans_ok = sum(1 for item in translated_lines if item and item.strip())
                _ocr_log(f'[Translate Result] ok={trans_ok} fail={len(original_texts)-trans_ok}')
                translate_succeeded = True
            except Exception as e:
                trans_fail = len(original_texts)
                translated_lines = [''] * len(original_texts)
                _ocr_log(f'[Translate ERROR] {e}')
        else:
            _ocr_log('[Translate] skipped (no translate_cfg)')

        _ocr_log('[Marker Generation]')
        skip_count = 0
        marker_id = 0
        for i, (m, text, quad) in enumerate(selected):
            translated = translated_lines[i] if i < len(translated_lines) else ''
            # 翻譯成功但譯文為空（LLM 判定無意義），跳過不建標號
            # 注意：API 失敗時 translate_succeeded=False，不做過濾以免誤刪全部標號
            # detect_only 模式：不做過濾（翻譯尚未進行）
            if not detect_only and translate_succeeded and not translated.strip():
                _ocr_log(f'  SKIP #{i+1}: empty translation (meaningless)')
                skip_count += 1
                continue
            marker_id += 1
            # 標號錨點：標號「靠」在文字框的哪個位置。
            #   竖排 → 靠右上：上邊中間 (cx, y0) 與右上角 (x1, y0) 的中點
            #   橫排 → 靠左上：左上角 (x0, y0)
            # 方向用合併後整塊的外接矩形長寬比判定：合併塊包含單字框（方形）
            # 時，用第一個 quad 的 _is_vertical 會誤判為橫排，改用整塊形狀。
            vertical = m['h'] > m['w']
            if vertical:
                nx = ((m['cx'] + m['x1']) / 2.0) / W
                ny = m['y0'] / H
            else:
                nx = m['x0'] / W
                ny = m['y0'] / H
            markers.append({
                'id': marker_id,
                'x': round(nx, 4),
                'y': round(ny, 4),
                'inside': 1,
                'text': translated,
                'original': text,
                'vertical': vertical,
            })
            _ocr_log(f'  Marker #{marker_id}: pos=({nx:.4f},{ny:.4f}) vertical={vertical} text={repr(text)[:40]} translated={repr(translated)[:40]}')
            yield {'type': 'progress', 'done': i + 1, 'total': len(selected)}

        _ocr_log(f'========== DONE page={img_name} markers={len(markers)} skip={skip_count} translated_ok={trans_ok} translated_fail={trans_fail} ==========')
        yield {'type': 'done', 'markers': markers,
               'translated_ok': trans_ok, 'translated_fail': trans_fail,
               'skipped': skip_count}
    except Exception as e:
        _ocr_log(f'[ERROR] page={img_name} error={e}')
        yield {'type': 'error', 'error': str(e)}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def stream_auto_ocr(img_name, lang='japan', reading_order='auto', translate_cfg=None,
                    debug=False):
    """Auto-OCR a single whole page.

    Thin, backward-compatible wrapper: turns the per-page event dicts into
    NDJSON strings. Use stream_auto_ocr_all() for the multi-page case."""
    for ev in _iter_page_events(img_name, lang=lang, reading_order=reading_order,
                               translate_cfg=translate_cfg, debug=debug):
        yield _ndjson(ev)


def _save_page_results(img_name, markers):
    """Persist one page's auto-OCR result: dialogues (TXT) + originals (cache).

    Pages that yield no markers are left untouched, so an empty detection result
    does not wipe existing manual labels on that page. Thread-safe."""
    if not markers:
        return
    from core.comic import parse_all_comics, save_all_comics, get_txt_file
    from ui.services.originals import save_originals

    normalized = [{
        'id': int(m['id']),
        'x': float(m['x']),
        'y': float(m['y']),
        'inside': 1,
        'text': m.get('text') or '',
    } for m in markers]
    with _SAVE_LOCK:
        all_data = parse_all_comics(get_txt_file())
        all_data[img_name] = normalized
        save_all_comics(get_txt_file(), all_data)

    originals = {m['id']: m.get('original') or '' for m in markers}
    save_originals(img_name, originals)


def translate_markers_for_page(img_name, markers, translate_cfg, debug=False):
    """Translate original texts in markers via API. Mutates markers in-place.

    Returns (trans_ok, trans_fail, markers) for convenience."""
    if not markers or not translate_cfg:
        return 0, len(markers), markers

    original_texts = [m.get('original', '') for m in markers]
    _ocr_log(f'[Translate] page={img_name} batch_length={len(original_texts)} lines')

    translated_lines = [''] * len(original_texts)
    trans_ok = 0
    trans_fail = 0
    translate_succeeded = False

    try:
        originals_dict = {i + 1: text for i, text in enumerate(original_texts)}
        md_content = export_markdown(originals_dict, page_name=img_name)
        system_prompt = format_for_llm(md_content)

        debug_dir = _get_debug_dir(img_name) if debug else None
        if debug_dir:
            try:
                with open(os.path.join(debug_dir, 'input.md'), 'w', encoding='utf-8') as f:
                    f.write(md_content)
                _ocr_log(f'[Debug] input.md saved')
            except Exception:
                pass

        from ui.services.translate import chat
        translated_md = chat([
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': md_content},
        ], translate_cfg, timeout=30)

        if debug_dir:
            try:
                with open(os.path.join(debug_dir, 'output.md'), 'w', encoding='utf-8') as f:
                    f.write(translated_md)
                _ocr_log(f'[Debug] output.md saved')
            except Exception:
                pass

        translations = extract_translations(translated_md)
        if translations:
            translated_lines = [translations.get(i + 1, '') for i in range(len(original_texts))]
        else:
            _ocr_log('[Translate] markdown parse failed, falling back to legacy method')
            translated = translate('\n'.join(original_texts), translate_cfg)
            translated_lines = assign_contextual_translations(original_texts, translated)

        trans_ok = sum(1 for item in translated_lines if item and item.strip())
        _ocr_log(f'[Translate Result] ok={trans_ok} fail={len(original_texts) - trans_ok}')
        translate_succeeded = True
    except Exception as e:
        trans_fail = len(original_texts)
        translated_lines = [''] * len(original_texts)
        _ocr_log(f'[Translate ERROR] page={img_name} {e}')

    skip_count = 0
    for i, m in enumerate(markers):
        translated = translated_lines[i] if i < len(translated_lines) else ''
        if translate_succeeded and not translated.strip():
            skip_count += 1
            m['_skip'] = True
        else:
            m['text'] = translated

    markers = [m for m in markers if not m.get('_skip')]
    for m in markers:
        m.pop('_skip', None)

    _ocr_log(f'[Translate DONE] page={img_name} markers={len(markers)} skip={skip_count} translated_ok={trans_ok}')
    return trans_ok, trans_fail, markers


def stream_auto_ocr_all(page_images, lang='japan', reading_order='auto', translate_cfg=None,
                        debug=False):
    """Auto-OCR EVERY page in `page_images`, streaming progress + debug events.

    Producer-consumer pipeline (like BallonsTranslator):
      Producer thread (main): detect → OCR → merge per page (fast).
      Consumer thread: translate completed pages in background (slow I/O).

    Detection of page N+1 overlaps with translation of page N, hiding
    translation latency behind OCR work.

    Each completed page is written back to the comic TXT and the originals cache
    as its translation finishes, so a later page error does not lose earlier results.

    Emits:
      {"type":"info","msg":...,"total_pages":N}
      {"type":"page_start","page":i,"total_pages":N,"img":name}
      {"type":"start","page":i,"total_pages":N,"img":name,"total":M}
      {"type":"progress","page":i,"total_pages":N,"img":name,"done":j,"total":M}
      {"type":"page_done","page":i,"total_pages":N,"img":name,
       "count":K,"translated_ok":ok,"translated_fail":fail}
      {"type":"log","msg":"..."}            (per-page result / error, for debugging)
      {"type":"done","total_pages":N,"total_markers":T,
       "per_page":{img:count},"errors":[{img,error}]}
      {"type":"error","error":"..."}        (fatal only)
    """
    import queue as _queue

    total_pages = len(page_images)
    yield _ndjson({'type': 'info', 'msg': f'開始自動 OCR：共 {total_pages} 頁', 'total_pages': total_pages})
    print(f'[auto-ocr] 開始處理 {total_pages} 頁')

    # No translation → just detect sequentially
    if not translate_cfg:
        print('[auto-ocr] 無翻譯設定，僅偵測')
        per_page = {}
        grand_total = 0
        errors = []
        for idx, img in enumerate(page_images, 1):
            yield _ndjson({'type': 'page_start', 'page': idx, 'total_pages': total_pages, 'img': img})
            try:
                markers = None
                for ev in _iter_page_events(img, lang=lang, reading_order=reading_order,
                                            translate_cfg=None, debug=debug, detect_only=True):
                    if ev['type'] == 'start':
                        yield _ndjson({'type': 'start', 'page': idx, 'total_pages': total_pages,
                                       'img': img, 'total': ev['total']})
                    elif ev['type'] == 'progress':
                        yield _ndjson({'type': 'progress', 'page': idx, 'total_pages': total_pages,
                                       'img': img, 'done': ev['done'], 'total': ev['total']})
                    elif ev['type'] == 'done':
                        markers = ev['markers']
                    elif ev['type'] == 'error':
                        raise RuntimeError(ev['error'])
                if markers is None:
                    raise RuntimeError('內部錯誤：未收到 done 事件')
                _save_page_results(img, markers)
                per_page[img] = len(markers)
                grand_total += len(markers)
                yield _ndjson({'type': 'page_done', 'page': idx, 'total_pages': total_pages,
                               'img': img, 'count': len(markers),
                               'translated_ok': 0, 'translated_fail': len(markers)})
            except Exception as e:
                errors.append({'img': img, 'error': str(e)})
                yield _ndjson({'type': 'log', 'msg': f'第 {idx}/{total_pages} 頁 {img} 失敗：{e}'})
        yield _ndjson({'type': 'done', 'total_pages': total_pages, 'total_markers': grand_total,
                       'per_page': per_page, 'errors': errors})
        return

    # ------------------------------------------------------------------
    # Producer-consumer pipeline
    # ------------------------------------------------------------------
    translate_q = _queue.Queue()
    event_q = _queue.Queue()
    stop_event = threading.Event()

    def _translate_worker():
        """Consumer: translate pages from the queue, save results, emit events."""
        while not stop_event.is_set() or not translate_q.empty():
            try:
                img, idx, markers = translate_q.get(timeout=0.5)
            except _queue.Empty:
                continue
            try:
                ok, fail, updated = translate_markers_for_page(
                    img, markers, translate_cfg, debug=debug)
                _save_page_results(img, updated)
                event_q.put(('page_done', idx, img, len(updated), ok, fail))
                print(f'[auto-ocr] 翻譯完成：第 {idx} 頁 {img}（ok={ok} fail={fail}）')
            except Exception as e:
                event_q.put(('page_error', idx, img, str(e)))
                print(f'[auto-ocr] 翻譯失敗：第 {idx} 頁 {img}：{e}')
            finally:
                translate_q.task_done()
        event_q.put(('worker_done',))

    worker = threading.Thread(target=_translate_worker, daemon=True)
    worker.start()
    print('[auto-ocr] 翻譯 worker 已啟動')

    per_page = {}
    grand_total = 0
    errors = []

    # ------------------------------------------------------------------
    # Producer loop: detect all pages (overlaps with translation worker)
    # ------------------------------------------------------------------
    for idx, img in enumerate(page_images, 1):
        yield _ndjson({'type': 'page_start', 'page': idx, 'total_pages': total_pages, 'img': img})
        print(f'[auto-ocr] 偵測第 {idx}/{total_pages} 頁：{img}')
        try:
            markers = None
            for ev in _iter_page_events(img, lang=lang, reading_order=reading_order,
                                        translate_cfg=None, debug=debug, detect_only=True):
                if ev['type'] == 'start':
                    yield _ndjson({'type': 'start', 'page': idx, 'total_pages': total_pages,
                                   'img': img, 'total': ev['total']})
                elif ev['type'] == 'progress':
                    yield _ndjson({'type': 'progress', 'page': idx, 'total_pages': total_pages,
                                   'img': img, 'done': ev['done'], 'total': ev['total']})
                elif ev['type'] == 'done':
                    markers = ev['markers']
                elif ev['type'] == 'error':
                    raise RuntimeError(ev['error'])

            if markers is None:
                raise RuntimeError('內部錯誤：未收到 done 事件')

            # Save OCR results immediately (text empty, original populated)
            _save_page_results(img, markers)
            per_page[img] = len(markers)
            grand_total += len(markers)

            # Push to translation queue (non-blocking; worker picks up)
            translate_q.put((img, idx, markers))
            print(f'[auto-ocr] 偵測第 {idx} 頁完成 → 已加入翻譯 queue（queue 大小：{translate_q.qsize()}）')
        except Exception as e:
            errors.append({'img': img, 'error': str(e)})
            yield _ndjson({'type': 'log', 'msg': f'第 {idx}/{total_pages} 頁 {img} 偵測失敗：{e}'})

    # ------------------------------------------------------------------
    # Wait for all translations to finish
    # ------------------------------------------------------------------
    print(f'[auto-ocr] 所有頁面偵測完成，等待翻譯 worker 完成...')
    yield _ndjson({'type': 'log', 'msg': '偵測完成，等待翻譯...'})

    translate_q.join()     # blocks until all queue items are task_done()
    stop_event.set()       # tell worker to exit
    worker.join(timeout=5) # wait for worker thread to finish

    # Drain event queue
    while not event_q.empty():
        ev = event_q.get_nowait()
        if ev[0] == 'page_done':
            _, pidx, pimg, count, ok, fail = ev
            yield _ndjson({'type': 'page_done', 'page': pidx, 'total_pages': total_pages,
                           'img': pimg, 'count': count,
                           'translated_ok': ok, 'translated_fail': fail})
        elif ev[0] == 'page_error':
            _, pidx, pimg, error = ev
            errors.append({'img': pimg, 'error': error})
            yield _ndjson({'type': 'log', 'msg': f'第 {pidx}/{total_pages} 頁 {pimg} 翻譯失敗：{error}'})

    yield _ndjson({'type': 'done', 'total_pages': total_pages, 'total_markers': grand_total,
                   'per_page': per_page, 'errors': errors})
    print(f'[auto-ocr] 完成：{total_pages} 頁，共 {grand_total} 個標號，{len(errors)} 頁失敗')
