import io
import os
import threading

from flask import Blueprint, jsonify, make_response, request, send_from_directory

from core.comic import get_comic_dir

from ui.config import NEIGHBOR_PREWARM_RADIUS
from ui.services.image_variants import Image, generate_variant_if_needed

images_bp = Blueprint('images', __name__)


@images_bp.route('/image/<path:filename>')
def serve_image(filename):
    file_path = os.path.join(get_comic_dir(), filename)
    if not os.path.exists(file_path):
        return jsonify({'error': f'File not found: {filename}'}), 404
    return send_from_directory(get_comic_dir(), filename)


@images_bp.route('/image_variant/<int:width>/<path:filename>')
def serve_image_variant(width, filename):
  # width maybe 'orig' in frontend; this route only for ints
  p = generate_variant_if_needed(width, filename)
  if p is None or not os.path.exists(p):
    return jsonify({'error': f'File not found: {filename}'}), 404
  # if variant path is under comic dir cache, serve from there
  # ensure safe send
  return send_from_directory(os.path.dirname(p), os.path.basename(p))


@images_bp.route('/api/speed_test')
def speed_test():
  # return a small generated JPEG to measure download speed
  if Image is None:
    # fallback small payload
    data = b'0' * 10240
    resp = make_response(data)
    resp.headers['Content-Type'] = 'application/octet-stream'
    return resp
  try:
    im = Image.new('RGB', (320, 200), color=(200, 200, 200))
    bio = io.BytesIO()
    im.save(bio, format='JPEG', quality=70)
    bio.seek(0)
    data = bio.read()
    resp = make_response(data)
    resp.headers['Content-Type'] = 'image/jpeg'
    return resp
  except Exception:
    data = b'0' * 10240
    resp = make_response(data)
    resp.headers['Content-Type'] = 'application/octet-stream'
    return resp


@images_bp.route('/debug/list_files')
def list_files():
    files = os.listdir(get_comic_dir())
    images = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]
    return jsonify({
        'directory': os.path.abspath(get_comic_dir()),
        'total_files': len(files),
        'images': images,
    })


@images_bp.route('/api/prewarm')
def api_prewarm():
  """Trigger neighbor prewarm. Query params: index (int) or img (name), radius (int optional)."""
  index = request.args.get('index')
  img = request.args.get('img')
  try:
    radius = int(request.args.get('radius', NEIGHBOR_PREWARM_RADIUS))
  except Exception:
    radius = NEIGHBOR_PREWARM_RADIUS

  files = [f for f in os.listdir(get_comic_dir()) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]
  files.sort()
  if index is not None:
    try:
      idx = int(index)
    except Exception:
      return jsonify({'error': 'invalid index'}), 400
  elif img is not None:
    try:
      idx = files.index(img)
    except Exception:
      return jsonify({'error': 'img not found'}), 404
  else:
    return jsonify({'error': 'index or img required'}), 400

  def _do():
    for i in range(max(0, idx-radius), min(len(files), idx+radius+1)):
      f = files[i]
      try:
        with Image.open(os.path.join(get_comic_dir(), f)) as im:
          ow, oh = im.size
          if ow > 1000:
            generate_variant_if_needed(1000, f)
          if ow > 2000:
            generate_variant_if_needed(2000, f)
      except Exception:
        continue

  try:
    threading.Thread(target=_do, daemon=True).start()
  except Exception:
    _do()

  return jsonify({'status': 'started'})
