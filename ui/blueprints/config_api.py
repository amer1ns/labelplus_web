from flask import Blueprint, jsonify, request

from core.comic import read_config, write_config

config_bp = Blueprint('config_api', __name__)


@config_bp.route('/api/log', methods=['POST'])
def api_log():
  data = request.json or {}
  msg = data.get('msg', '')
  level = data.get('level', 'info')
  try:
    print(f'CLIENT_LOG [{level}]: {msg}')
  except Exception:
    pass
  return jsonify({'status': 'ok'})


@config_bp.route('/api/debug', methods=['GET'])
def api_debug_get():
  cfg = read_config()
  return jsonify({'status': 'ok', 'debug_ocr': bool(cfg.get('debug_ocr', False))})


@config_bp.route('/api/debug/toggle', methods=['POST'])
def api_debug_toggle():
  cfg = read_config()
  new_val = not bool(cfg.get('debug_ocr', False))
  cfg['debug_ocr'] = new_val
  try:
    write_config(cfg)
    return jsonify({'status': 'ok', 'debug_ocr': new_val})
  except Exception:
    return jsonify({'status': 'error', 'error': 'failed to write config'}), 500


@config_bp.route('/api/config', methods=['GET', 'POST'])
def api_config():
  """Get or set simple JSON config stored next to the app as config.json
  (marker size, OCR / translate API settings — persists across comic folders)."""
  if request.method == 'GET':
    return jsonify({'status': 'ok', 'config': read_config()})

  # POST: update
  data = request.json or {}
  cfg = read_config()
  out = {}

  # accept marker_scale (legacy) or marker_px
  if 'marker_px' in data:
    try:
      mp = float(data.get('marker_px'))
      mp = max(4.0, min(1000.0, mp))
      out['marker_px'] = mp
    except Exception:
      return jsonify({'status': 'error', 'error': 'invalid marker_px'}), 400
  if 'marker_scale' in data:
    try:
      ms = float(data.get('marker_scale'))
      ms = max(0.2, min(3.0, ms))
      out['marker_scale'] = ms
    except Exception:
      return jsonify({'status': 'error', 'error': 'invalid marker_scale'}), 400

  # ocr settings (nested, shallow-merged)
  if 'ocr' in data:
    ocr_in = data.get('ocr')
    if not isinstance(ocr_in, dict):
      return jsonify({'status': 'error', 'error': 'invalid ocr'}), 400
    merged_ocr = cfg.get('ocr') if isinstance(cfg.get('ocr'), dict) else {}
    merged_ocr.update(ocr_in)
    out['ocr'] = merged_ocr

  cfg.update(out)
  try:
    write_config(cfg)
    return jsonify({'status': 'ok', 'config': cfg})
  except Exception:
    return jsonify({'status': 'error', 'error': 'failed to write config'}), 500
