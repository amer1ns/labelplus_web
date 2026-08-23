import os

from flask import Blueprint, jsonify, request

from core.comic import get_comic_dir, get_txt_file, parse_all_comics, save_all_comics

dialogues_bp = Blueprint('dialogues', __name__)


@dialogues_bp.route('/api/get_dialogues')
def get_dialogues():
    img_name = request.args.get('img')
    if not img_name:
        return jsonify({'error': 'No image specified'}), 400

    all_data = parse_all_comics(get_txt_file())
    dialogues = all_data.get(img_name, [])

    img_path = os.path.join(get_comic_dir(), img_name)
    if not os.path.exists(img_path):
        return jsonify({'error': f'Image not found: {img_path}'}), 404

    return jsonify({
        'image': f'/image/{img_name}',
        'dialogues': dialogues,
    })


@dialogues_bp.route('/api/update_text', methods=['POST'])
def update_text():
    data = request.json
    img_name = data.get('img')
    dialogue_id = data.get('id')
    new_text = data.get('text')

    if not img_name or dialogue_id is None:
        return jsonify({'error': 'Missing params'}), 400

    all_data = parse_all_comics(get_txt_file())
    dialogues = all_data.get(img_name)
    if not dialogues:
        return jsonify({'error': 'Image not found in TXT'}), 404

    for d in dialogues:
        if d['id'] == dialogue_id:
            d['text'] = new_text
            break
    else:
        return jsonify({'error': 'Dialogue ID not found'}), 404

    save_all_comics(get_txt_file(), all_data)
    return jsonify({'status': 'ok'})


@dialogues_bp.route('/api/save_dialogues', methods=['POST'])
def save_dialogues():
    data = request.json
    img_name = data.get('img')
    dialogues = data.get('dialogues')
    if not img_name or dialogues is None:
        return jsonify({'error': 'Missing params'}), 400
    if not isinstance(dialogues, list):
        return jsonify({'error': 'Dialogues must be a list'}), 400

    normalized = []
    for item in dialogues:
        try:
            normalized.append({
                'id': int(item.get('id')),
                'x': float(item.get('x')),
                'y': float(item.get('y')),
                'inside': 1 if int(item.get('inside', 1)) == 1 else 2,
                'text': item.get('text') or '',
            })
        except Exception:
            return jsonify({'error': 'Invalid dialogue item format'}), 400

    # 統一編號：保持前端傳入的「標註順序」，重排 id 為連續 1,2,3…
    # 前端刪除標號後（4→3、5→4）也做同樣前移，這裡是保險——不管前端傳什麼，
    # txt 一定連續，並把結果回傳讓前端同步，避免前後端 id 不一致。
    for i, d in enumerate(normalized):
        d['id'] = i + 1

    all_data = parse_all_comics(get_txt_file())
    all_data[img_name] = normalized
    save_all_comics(get_txt_file(), all_data)
    return jsonify({'status': 'ok', 'dialogues': normalized})
