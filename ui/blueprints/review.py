from flask import Blueprint, jsonify, render_template, request

from ui.services import review_store

review_bp = Blueprint('review', __name__)


@review_bp.route('/review')
def review_page():
    return render_template('review.html')


@review_bp.route('/api/review/dashboard')
def review_dashboard():
    return jsonify({'status': 'ok', 'dashboard': review_store.dashboard()})


@review_bp.route('/api/review/items', methods=['GET', 'POST'])
def review_items():
    if request.method == 'GET':
        items = review_store.get_items()
        status = request.args.get('status')
        q = (request.args.get('q') or '').strip().lower()
        if status:
            if status == 'new':
                items = [it for it in items if it.get('status') == 'new']
            elif status == 'mastered':
                items = [it for it in items if it.get('status') == 'mastered']
            elif status in ('review', 'learning'):
                items = [it for it in items if it.get('status') in ('review', 'learning')]
        if q:
            items = [it for it in items
                     if q in (it.get('original') or '').lower()
                     or q in (it.get('translation') or '').lower()
                     or q in (it.get('grammar') or '').lower()
                     or q in (it.get('note') or '').lower()]
        items.sort(key=lambda it: it.get('created_at') or '', reverse=True)
        return jsonify({'status': 'ok', 'items': items})

    # POST: capture (create or update) 考點s from the editor ⭐ button.
    # One sentence can hold several difficulties: `entries` is a list of
    # {item_id?, point, grammar, note}; `meaning/example/confusion` are
    # sentence-level and shared by every card. `removed_ids` deletes cards
    # whose rows the user removed.
    data = request.json or {}
    img = data.get('img')
    marker_id = data.get('marker_id')
    if img is None or marker_id is None:
        return jsonify({'error': 'Missing params'}), 400
    try:
        items, created = review_store.capture_items(
            img, marker_id,
            original=data.get('original'),
            translation=data.get('translation'),
            entries=data.get('entries'),
            shared=data,
            removed_ids=data.get('removed_ids'),
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'status': 'ok', 'items': items, 'created': created})


@review_bp.route('/api/review/migrate', methods=['POST'])
def review_migrate():
    """標號重排後遷移考點 marker_id。mapping: {舊id: 新id}。"""
    data = request.json or {}
    img = data.get('img')
    mapping = data.get('mapping') or {}
    deleted = data.get('deleted') or []
    if not img or not isinstance(mapping, dict):
        return jsonify({'error': 'Missing params'}), 400
    try:
        changed, orphan = review_store.migrate_marker_ids(img, mapping, deleted)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'status': 'ok', 'changed': changed, 'orphan': orphan})


@review_bp.route('/api/review/items/<item_id>', methods=['GET', 'PUT', 'DELETE'])
def review_item(item_id):
    if request.method == 'GET':
        it = next((x for x in review_store.get_items() if x.get('id') == item_id), None)
        if not it:
            return jsonify({'error': 'Item not found'}), 404
        return jsonify({'status': 'ok', 'item': it})

    if request.method == 'PUT':
        data = request.json or {}
        it = review_store.update_item(item_id, data)
        if not it:
            return jsonify({'error': 'Item not found'}), 404
        return jsonify({'status': 'ok', 'item': it})

    # DELETE
    if review_store.delete_item(item_id):
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Item not found'}), 404


@review_bp.route('/api/review/items/<item_id>/grade', methods=['POST'])
def review_grade(item_id):
    grade = (request.json or {}).get('grade')
    it = review_store.grade_item(item_id, grade)
    if not it:
        return jsonify({'error': 'Item not found'}), 404
    return jsonify({'status': 'ok', 'item': it})


@review_bp.route('/api/review/items/<item_id>/state', methods=['POST'])
def review_state(item_id):
    action = (request.json or {}).get('action')
    it = review_store.set_item_state(item_id, action)
    if not it:
        return jsonify({'error': 'Item not found or bad action'}), 404
    return jsonify({'status': 'ok', 'item': it})


@review_bp.route('/api/review/items/<item_id>/ai', methods=['POST'])
def review_ai(item_id):
    """AI 拆解單一考點：語法＋含義＋例句＋易混淆（就地填回並儲存）。
    若 AI 依譯文修正了 OCR 原文，也會一併套用到該考點的原文。"""
    items = review_store.get_items()
    it = next((x for x in items if x.get('id') == item_id), None)
    if not it:
        return jsonify({'error': 'Item not found'}), 404
    bd = review_store.breakdown(it.get('original'), it.get('translation'))
    if not bd:
        return jsonify({'error': 'AI 拆解失敗（請確認 OCR 設定中的 API Key）'}), 502
    fields = {k: bd.get(k) for k in ('grammar', 'meaning', 'example', 'confusion')}
    corrected = (bd.get('corrected_original') or '').strip()
    if corrected and corrected != (it.get('original') or '').strip():
        fields['original'] = corrected
    it = review_store.update_item(item_id, fields)
    return jsonify({'status': 'ok', 'item': it, 'corrected': corrected})


@review_bp.route('/api/review/breakdown', methods=['POST'])
def review_breakdown():
    """給編輯框 ⭐ 視窗用的純拆解（不儲存），方便先看再存。"""
    data = request.json or {}
    bd = review_store.breakdown(data.get('original'), data.get('translation'))
    if not bd:
        return jsonify({'error': 'AI 拆解失敗（請確認 OCR 設定中的 API Key）'}), 502
    return jsonify({'status': 'ok', 'breakdown': bd})
