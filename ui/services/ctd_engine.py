"""CTD (Comic Text Detector) 檢測引擎 — 獨立實現。

CTD 是 BallonsTranslator 用於漫畫的專用文字檢測模型，檢測框精度遠高於
PaddleOCR 的通用 DB 檢測器（誤差 <0.5% vs 5%）。本模組自 BallonsTranslator
提取核心演算法（不依賴 BT 專案結構）：

- TextDetBaseDNN：OpenCV DNN 跑 ONNX 模型（CPU）
- letterbox：縮放 + padding 預處理
- SegDetectorRepresenter（DB 分割後處理）：contours → mini boxes → unclip

偵測走 CTD 的 DB 分割路徑（比 YOLO bbox 更全，BT 預設使用）。
輸出座標已映射回「原圖像素」（與瀏覽器顯示的視覺空間一致）。

依賴：torch、cv2、numpy、pyclipper、shapely（allinone env 已齊全）。
模型：comictextdetector.pt.onnx（CPU）。
"""
import os

import numpy as np
import cv2
import pyclipper
from shapely.geometry import Polygon

# 模型路徑：預設為專案根目錄下的相對路徑（可執行 download_ctd_model.bat 下載放置）；
# 由 main.py 啟動時解析為絕對路徑寫入環境變數，也可自行設定 CTD_MODEL_PATH 覆蓋。
_CTD_MODEL = os.environ.get('CTD_MODEL_PATH', '').strip() or r'.\models\comictextdetector.pt.onnx'

_DETECT_SIZE = 1024
_SEG_THRESH = 0.3
# 膨脹後的 box 含背景，box_score_fast 平均分會偏低；這裡只用它濾掉完全空白
# 的假 contour（大小過濾 _get_mini_boxes 已去掉大部分雜訊）。
_BOX_THRESH = 0.6
_UNCLIP_RATIO = 1.0

_net = None


# --- model (OpenCV DNN, CPU) -------------------------------------------------
class _TextDetBaseDNN:
    def __init__(self, model_path):
        self.input_size = _DETECT_SIZE
        self.model = cv2.dnn.readNetFromONNX(model_path)
        self.uoln = self.model.getUnconnectedOutLayersNames()

    def __call__(self, im_in):
        blob = cv2.dnn.blobFromImage(im_in, scalefactor=1 / 255.0,
                                     size=(self.input_size, self.input_size))
        self.model.setInput(blob)
        blks, mask, lines_map = self.model.forward(self.uoln)
        return blks, mask, lines_map


# --- preprocessing (from BT utils/imgproc_utils.py) --------------------------
def _letterbox(im, new_shape=(1024, 1024), color=(0, 0, 0), stride=64):
    shape = im.shape[:2]
    if not isinstance(new_shape, tuple):
        new_shape = (new_shape, new_shape)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    dh, dw = int(dh), int(dw)
    if shape[::-1] != new_unpad:
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    im = cv2.copyMakeBorder(im, 0, dh, 0, dw, cv2.BORDER_CONSTANT, value=color)
    return im, (dw, dh)


def _preprocess_img(img):
    img_in, (dw, dh) = _letterbox(img, new_shape=_DETECT_SIZE)
    return img_in, int(dw), int(dh)


# --- DB segmentation postprocess (from BT modules/textdetector/db_utils.py) --
def _unclip(box, unclip_ratio=1.5):
    poly = Polygon(box)
    distance = poly.area * unclip_ratio / poly.length
    offset = pyclipper.PyclipperOffset()
    offset.AddPath(box, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    expanded = np.array(offset.Execute(distance))
    return expanded


def _get_mini_boxes(contour):
    bounding_box = cv2.minAreaRect(contour)
    points = sorted(list(cv2.boxPoints(bounding_box)), key=lambda x: x[0])
    index_1, index_2, index_3, index_4 = 0, 1, 2, 3
    if points[1][1] > points[0][1]:
        index_1, index_4 = 0, 1
    else:
        index_1, index_4 = 1, 0
    if points[3][1] > points[2][1]:
        index_2, index_3 = 2, 3
    else:
        index_2, index_3 = 3, 2
    box = [points[index_1], points[index_2], points[index_3], points[index_4]]
    return box, min(bounding_box[1])


def _box_score_fast(bitmap, _box):
    h, w = bitmap.shape[:2]
    box = _box.copy()
    xmin = np.clip(np.floor(box[:, 0].min()).astype(np.int64), 0, w - 1)
    xmax = np.clip(np.ceil(box[:, 0].max()).astype(np.int64), 0, w - 1)
    ymin = np.clip(np.floor(box[:, 1].min()).astype(np.int64), 0, h - 1)
    ymax = np.clip(np.ceil(box[:, 1].max()).astype(np.int64), 0, h - 1)
    mask = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
    box[:, 0] = box[:, 0] - xmin
    box[:, 1] = box[:, 1] - ymin
    cv2.fillPoly(mask, box.reshape(1, -1, 2).astype(np.int32), 1)
    if bitmap.dtype == np.float16:
        bitmap = bitmap.astype(np.float32)
    return cv2.mean(bitmap[ymin:ymax + 1, xmin:xmax + 1], mask)[0]


def _boxes_from_bitmap(pred, bitmap, dest_width, dest_height):
    """DB 分割 → 字符級文本框 4 點（原圖座標）+ 分數（與 BT boxes_from_bitmap 相同）。

    不做膨脹，輸出緊貼字符的框；由 _group_chars 聚合為文本行。
    """
    height, width = bitmap.shape
    contours, _ = cv2.findContours((bitmap * 255).astype(np.uint8),
                                   cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    num_contours = min(len(contours), 1000)
    boxes = np.zeros((num_contours, 4, 2), dtype=np.int64)
    scores = np.zeros((num_contours,), dtype=np.float32)
    for index in range(num_contours):
        contour = contours[index].squeeze(1)
        points, sside = _get_mini_boxes(contour)
        if sside < 2:
            continue
        points = np.array(points)
        score = _box_score_fast(pred, contour)
        box = _unclip(points, unclip_ratio=_UNCLIP_RATIO).reshape(-1, 1, 2)
        box, sside = _get_mini_boxes(box)
        if sside < 2:
            continue
        box = np.array(box)
        box[:, 0] = np.clip(np.round(box[:, 0] / width * dest_width), 0, dest_width)
        box[:, 1] = np.clip(np.round(box[:, 1] / height * dest_height), 0, dest_height)
        boxes[index, :, :] = box.astype(np.int64)
        scores[index] = score
    return boxes, scores


def _judge_direction(chars, med_h, med_w):
    """依字符框之間的「水平相連」vs「垂直相連」票數判斷頁面主方向。"""
    h_score = 0
    v_score = 0
    for i, a in enumerate(chars):
        for b in chars[i + 1:]:
            x_overlap = min(a['x1'], b['x1']) - max(a['x0'], b['x0'])
            y_overlap = min(a['y1'], b['y1']) - max(a['y0'], b['y0'])
            if y_overlap > 0:
                gap = max(a['x0'] - b['x1'], b['x0'] - a['x1'])
                if gap < med_w * 1.5:
                    h_score += 1
            if x_overlap > 0:
                gap = max(a['y0'] - b['y1'], b['y0'] - a['y1'])
                if gap < med_h * 1.5:
                    v_score += 1
    return 'vertical' if v_score > h_score else 'horizontal'


def _group_horizontal(chars, med_h, med_w):
    """橫排聚合：垂直中心聚類成行帶，行帶內按 x 切分。"""
    bands = []
    for c in sorted(chars, key=lambda c: c['cy']):
        placed = False
        for b in bands:
            if abs(c['cy'] - b['cy']) <= med_h * 0.6:
                b['chars'].append(c)
                b['cy'] = sum(cc['cy'] for cc in b['chars']) / len(b['chars'])
                placed = True
                break
        if not placed:
            bands.append({'cy': c['cy'], 'chars': [c]})
    rows = []
    for b in bands:
        seg = []
        for c in sorted(b['chars'], key=lambda c: c['x0']):
            if seg and c['x0'] - seg[-1]['x1'] > med_w * 1.5:
                rows.append(seg)
                seg = []
            seg.append(c)
        if seg:
            rows.append(seg)
    return rows


def _group_vertical(chars, med_h, med_w):
    """竪排聚合：水平中心聚類成列帶，列帶內按 y 切分。"""
    cols = []
    for c in sorted(chars, key=lambda c: c['cx']):
        placed = False
        for b in cols:
            if abs(c['cx'] - b['cx']) <= med_w * 0.6:
                b['chars'].append(c)
                b['cx'] = sum(cc['cx'] for cc in b['chars']) / len(b['chars'])
                placed = True
                break
        if not placed:
            cols.append({'cx': c['cx'], 'chars': [c]})
    rows = []
    for b in cols:
        seg = []
        for c in sorted(b['chars'], key=lambda c: c['cy']):
            if seg and c['y0'] - seg[-1]['y1'] > med_h * 1.5:
                rows.append(seg)
                seg = []
            seg.append(c)
        if seg:
            rows.append(seg)
    return rows


def _group_chars(boxes, scores):
    """把字符級框聚合為文本行/列（原圖座標）。

    先判斷頁面主方向（橫/竪），再用對應規則聚合：
    - 橫排：y 聚類成行帶 → x 切分成行
    - 竪排：x 聚類成列帶 → y 切分成列

    回傳 [{quad, score}, ...]。
    """
    if not len(boxes):
        return []
    char_info = []
    for box, score in zip(boxes, scores):
        xs = box[:, 0]
        ys = box[:, 1]
        char_info.append({
            'x0': float(xs.min()), 'y0': float(ys.min()),
            'x1': float(xs.max()), 'y1': float(ys.max()),
            'cx': (float(xs.min()) + float(xs.max())) / 2,
            'cy': (float(ys.min()) + float(ys.max())) / 2,
            'score': float(score),
        })
    hs = sorted(max(0.1, c['y1'] - c['y0']) for c in char_info)
    med_h = hs[len(hs) // 2]
    ws = sorted(max(0.1, c['x1'] - c['x0']) for c in char_info)
    med_w = ws[len(ws) // 2]

    direction = _judge_direction(char_info, med_h, med_w)
    rows = (_group_vertical(char_info, med_h, med_w)
            if direction == 'vertical'
            else _group_horizontal(char_info, med_h, med_w))

    out = []
    for seg in rows:
        x0 = min(c['x0'] for c in seg)
        y0 = min(c['y0'] for c in seg)
        x1 = max(c['x1'] for c in seg)
        y1 = max(c['y1'] for c in seg)
        # 過濾太小/太扁的框（分割假陽性）：寬高任一維小於半字高即視為雜訊
        if min(x1 - x0, y1 - y0) < med_h * 0.4:
            continue
        q = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        out.append({'quad': q, 'score': max(c['score'] for c in seg)})
    return out


def _db_boxes(lines_map, im_h, im_w, dw, dh):
    """lines_map（DB 輸出）→ [{quad, score}, ...]（原圖座標）。

    流程：分割 → 字符級框 → score 過濾 → 按行聚合（_group_chars）。
    """
    # 去掉 letterbox padding
    lines_map = lines_map[..., :_DETECT_SIZE - dh, :_DETECT_SIZE - dw]
    pred = lines_map[0, 0]                       # 文本區域概率圖 (H, W)
    segmentation = pred > _SEG_THRESH
    boxes, scores = _boxes_from_bitmap(pred, segmentation, im_w, im_h)
    idx = np.where(scores > _BOX_THRESH)
    boxes, scores = boxes[idx], scores[idx]
    return _group_chars(boxes, scores)


# --- public API ---------------------------------------------------------------
def _ensure_net():
    global _net
    if _net is None:
        if not os.path.exists(_CTD_MODEL):
            raise RuntimeError(
                f'找不到 CTD 模型（{_CTD_MODEL}）：請先在專案根目錄執行 '
                'download_ctd_model.bat 下載，或用環境變數 CTD_MODEL_PATH 指定模型位置')
        _net = _TextDetBaseDNN(_CTD_MODEL)
    return _net


def _aabb(blk):
    xs = [p[0] for p in blk['quad']]
    ys = [p[1] for p in blk['quad']]
    return (min(xs), min(ys), max(xs), max(ys))


def _remove_nested(blocks):
    """過濾被其他較大框大幅覆蓋的重複框（DB 分割有時在行框內又產生子框）。"""
    if len(blocks) <= 1:
        return blocks
    boxes = [_aabb(b) for b in blocks]
    keep = []
    for i, a in enumerate(blocks):
        ax0, ay0, ax1, ay1 = boxes[i]
        aa = max(1.0, (ax1 - ax0) * (ay1 - ay0))
        nested = False
        for j, b in enumerate(blocks):
            if i == j:
                continue
            bx0, by0, bx1, by1 = boxes[j]
            ix0 = max(ax0, bx0)
            iy0 = max(ay0, by0)
            ix1 = min(ax1, bx1)
            iy1 = min(ay1, by1)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inter = (ix1 - ix0) * (iy1 - iy0)
            # 被更大的框覆蓋超過 60% → 視為重複子框
            if inter / aa > 0.6 and (bx1 - bx0) * (by1 - by0) > aa:
                nested = True
                break
        if not nested:
            keep.append(a)
    return keep


def _deduplicate_iou(blocks, iou_thresh=0.3):
    """移除 IoU 過高的重複框，保留分數較高的。

    DB 分割常對同一文字區域產生多個略微偏移的框（重疊但不完全嵌套），
    _remove_nested 無法過濾。此函數用 IoU（交集/較小框面積）做二次去重。
    """
    if len(blocks) <= 1:
        return blocks
    indexed = sorted(enumerate(blocks),
                     key=lambda x: x[1].get('score', 0), reverse=True)
    keep_mask = [True] * len(blocks)
    for ai, (i, a) in enumerate(indexed):
        if not keep_mask[i]:
            continue
        ax0, ay0, ax1, ay1 = _aabb(a)
        aa = max(1.0, (ax1 - ax0) * (ay1 - ay0))
        for bi, (j, b) in enumerate(indexed):
            if bi <= ai or not keep_mask[j]:
                continue
            bx0, by0, bx1, by1 = _aabb(b)
            ix0 = max(ax0, bx0)
            iy0 = max(ay0, by0)
            ix1 = min(ax1, bx1)
            iy1 = min(ay1, by1)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inter = (ix1 - ix0) * (iy1 - iy0)
            bb = max(1.0, (bx1 - bx0) * (by1 - by0))
            if inter / min(aa, bb) > iou_thresh:
                keep_mask[j] = False
    return [b for i, b in enumerate(blocks) if keep_mask[i]]


def detect_blocks(img_bgr):
    """CTD 偵測（BGR numpy）→ [{quad, score}, ...]（原圖像素座標）。

    ``img_bgr`` 需為「視覺空間」（已 exif 轉置）的 BGR 圖。quad 為 4 點
    多邊形（軸對齊文字時即矩形），座標與瀏覽器顯示的圖片對應。
    """
    net = _ensure_net()
    im_h, im_w = img_bgr.shape[:2]
    img_in, dw, dh = _preprocess_img(img_bgr)
    _blks, _mask, lines_map = net(img_in)
    blocks = _db_boxes(lines_map, im_h, im_w, dw, dh)
    blocks = _remove_nested(blocks)
    return _deduplicate_iou(blocks)


def recognize_blocks(ocr, img_bgr, blocks, run_ocr=None, extract_items=None,
                     save_crops_dir=None):
    """對每個檢測框裁切 → PaddleOCR 識別 → 填入 block['text']。

    ``blocks``：detect_blocks 回傳的 list（dict with 'quad'）；每個元素原地
    加上 ``'text'``。

    ``save_crops_dir``：若提供，將每個裁切圖保存到該目錄（調試用）。
    """
    import tempfile
    from PIL import Image
    if run_ocr is None or extract_items is None:
        from ui.services.ocr_engine import _run_ocr, _extract_text_items
        run_ocr = run_ocr or _run_ocr
        extract_items = extract_items or _extract_text_items
    if save_crops_dir:
        os.makedirs(save_crops_dir, exist_ok=True)
    for blk_idx, blk in enumerate(blocks):
        xs = [p[0] for p in blk['quad']]
        ys = [p[1] for p in blk['quad']]
        x0, y0 = int(min(xs)), int(min(ys))
        x1, y1 = int(max(xs)), int(max(ys))
        # 只做極小的擴邊（避免把相鄰不同位置的文字也裁進來干擾辨識），
        # 貼邊丟字改由下方「左右白邊」解決，不靠擴張裁剪範圍。
        ih, iw = img_bgr.shape[:2]
        x0 = max(0, x0 - 4)
        y0 = max(0, y0 - 4)
        x1 = min(iw, x1 + 4)
        y1 = min(ih, y1 + 4)
        crop = img_bgr[y0:y1, x0:x1]
        if crop is None or crop.size == 0:
            blk['text'] = ''
            continue
        crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        # PaddleOCR rec 對貼邊的字符容易丟字（尤其最左/最右）：左右各補
        # 白邊再識別。寬度適中，太大會讓超寬圖辨識失敗。
        ch, cw = crop_rgb.shape[:2]
        side = max(40, min(150, int(ch * 0.5)))
        white = np.full((ch, side, 3), 255, np.uint8)
        crop_rgb = np.concatenate([white, crop_rgb, white], axis=1)
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        tmp.close()
        try:
            Image.fromarray(crop_rgb).save(tmp.name, format='PNG')
            result = run_ocr(ocr, tmp.name)
            items = extract_items(result)
            blk['text'] = '\n'.join(t for _, t, _ in items)
        except Exception:
            blk['text'] = ''
        finally:
            if save_crops_dir and blk['text']:
                try:
                    crop_path = os.path.join(save_crops_dir, f'block_{blk_idx:03d}.png')
                    Image.fromarray(crop_rgb).save(crop_path, format='PNG')
                except Exception:
                    pass
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
    return blocks
