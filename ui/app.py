import os
import io
import threading
import json
from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, make_response

from core.comic import get_comic_dir, get_txt_file, parse_all_comics, save_all_comics

# optional dependency: Pillow. Install with `pip install Pillow`.
try:
  from PIL import Image
except Exception:
  Image = None

# number of images to prewarm on startup (first N)
try:
  PREWARM_COUNT = int(os.environ.get('PREWARM_COUNT', '8'))
except Exception:
  PREWARM_COUNT = 8
# neighbor prewarm radius when flipping pages
try:
  NEIGHBOR_PREWARM_RADIUS = int(os.environ.get('NEIGHBOR_PREWARM_RADIUS', '2'))
except Exception:
  NEIGHBOR_PREWARM_RADIUS = 2

app = Flask(__name__)


@app.after_request
def _no_cache_html(resp):
    if resp.content_type and resp.content_type.startswith('text/html'):
        resp.headers['Cache-Control'] = 'no-store'
        resp.headers['Pragma'] = 'no-cache'
    return resp


def _serve(mode='label', initial_img=None, initial_dpi=None, initial_scale=None):
  all_data = parse_all_comics(get_txt_file())
  images = list(all_data.keys())
  images.sort()
  return render_template_string(HTML_TEMPLATE, images=images, mode=mode, initial_img=initial_img, initial_dpi=initial_dpi, initial_scale=initial_scale)


@app.route('/')
def index():
    all_data = parse_all_comics(get_txt_file())
    images = list(all_data.keys())
    images.sort()
    if images:
        return redirect(f'/mark/{images[0]}')
    return _serve()


@app.route('/label')
def label_mode():
    return _serve('label')


@app.route('/input')
def input_mode():
    return _serve('input')


@app.route('/input/<path:img>')
def input_image(img):
  # support URL like /input/003.png/dpi-72 or /input/003.png/scale-1.25
  dpi = None
  scale = None
  if '/scale-' in img:
    parts = img.split('/scale-')
    img = parts[0]
    try:
      scale = float(parts[1])
    except Exception:
      scale = None
  elif '/dpi-' in img:
    parts = img.split('/dpi-')
    img = parts[0]
    try:
      dpi = int(parts[1])
    except Exception:
      dpi = None
  return _serve('input', img, initial_dpi=dpi, initial_scale=scale)


@app.route('/mark/<path:img>')
def mark_image(img):
  dpi = None
  scale = None
  if '/scale-' in img:
    parts = img.split('/scale-')
    img = parts[0]
    try:
      scale = float(parts[1])
    except Exception:
      scale = None
  elif '/dpi-' in img:
    parts = img.split('/dpi-')
    img = parts[0]
    try:
      dpi = int(parts[1])
    except Exception:
      dpi = None
  return _serve('label', img, initial_dpi=dpi, initial_scale=scale)


@app.route('/api/get_dialogues')
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


@app.route('/api/update_text', methods=['POST'])
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


@app.route('/api/save_dialogues', methods=['POST'])
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

    all_data = parse_all_comics(get_txt_file())
    all_data[img_name] = normalized
    save_all_comics(get_txt_file(), all_data)
    return jsonify({'status': 'ok'})


@app.route('/image/<path:filename>')
def serve_image(filename):
    file_path = os.path.join(get_comic_dir(), filename)
    if not os.path.exists(file_path):
        return jsonify({'error': f'File not found: {filename}'}), 404
    return send_from_directory(get_comic_dir(), filename)


def _cache_path_for(width, filename):
  base = get_comic_dir()
  cache_dir = os.path.join(base, '.cache', str(width))
  os.makedirs(cache_dir, exist_ok=True)
  return os.path.join(cache_dir, filename)


def generate_variant_if_needed(width, filename):
  """Generate resized variant at `width` if original is larger. Returns path to file to serve."""
  orig_path = os.path.join(get_comic_dir(), filename)
  if not os.path.exists(orig_path):
    return None
  # if Pillow not available, just return original
  if Image is None:
    return orig_path
  try:
    with Image.open(orig_path) as im:
      ow, oh = im.size
      if ow <= width:
        return orig_path
      out_path = _cache_path_for(width, filename)
      if os.path.exists(out_path):
        return out_path
      # ensure parent dir
      os.makedirs(os.path.dirname(out_path), exist_ok=True)
      # compute height preserving aspect
      nh = int(oh * (width / ow))
      im = im.convert('RGB')
      im = im.resize((width, nh), Image.LANCZOS)
      im.save(out_path, format='JPEG', quality=85)
      return out_path
  except Exception:
    return orig_path


@app.route('/image_variant/<int:width>/<path:filename>')
def serve_image_variant(width, filename):
  # width maybe 'orig' in frontend; this route only for ints
  p = generate_variant_if_needed(width, filename)
  if p is None or not os.path.exists(p):
    return jsonify({'error': f'File not found: {filename}'}), 404
  # if variant path is under comic dir cache, serve from there
  # ensure safe send
  return send_from_directory(os.path.dirname(p), os.path.basename(p))


@app.route('/api/speed_test')
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


@app.route('/debug/list_files')
def list_files():
    files = os.listdir(get_comic_dir())
    images = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]
    return jsonify({
        'directory': os.path.abspath(get_comic_dir()),
        'total_files': len(files),
        'images': images,
    })

@app.route('/api/log', methods=['POST'])
def api_log():
  data = request.json or {}
  msg = data.get('msg', '')
  level = data.get('level', 'info')
  try:
    print(f'CLIENT_LOG [{level}]: {msg}')
  except Exception:
    pass
  return jsonify({'status': 'ok'})


@app.route('/api/prewarm')
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


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
  """Get or set simple JSON config stored in the comic directory as config.json"""
  cfg_path = os.path.join(get_comic_dir(), 'config.json')
  if request.method == 'GET':
    if os.path.exists(cfg_path):
      try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
          data = json.load(f)
        return jsonify({'status': 'ok', 'config': data})
      except Exception:
        return jsonify({'status': 'error', 'error': 'failed to read config'}), 500
    else:
      return jsonify({'status': 'ok', 'config': {}})

  # POST: update
  data = request.json or {}
  # accept marker_scale (legacy) or marker_px
  out = {}
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

  # merge with existing
  cfg = {}
  if os.path.exists(cfg_path):
    try:
      with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    except Exception:
      cfg = {}
  cfg.update(out)
  try:
    with open(cfg_path, 'w', encoding='utf-8') as f:
      json.dump(cfg, f, ensure_ascii=False, indent=2)
    return jsonify({'status': 'ok', 'config': cfg})
  except Exception:
    return jsonify({'status': 'error', 'error': 'failed to write config'}), 500
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<title>漫畫標號器</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;}
  html,body{height:100%;overflow:hidden;}
  body{background:#0d0e14;color:#eef;font-family:system-ui,-apple-system,'PingFang TC','Microsoft JhengHei',sans-serif;position:fixed;inset:0;touch-action:none;}
  @keyframes fadeIn{from{opacity:0;}to{opacity:1;}}
  #app{position:absolute;inset:0;display:flex;}
  #center{flex:1;min-width:0;display:flex;flex-direction:column;position:relative;}
  #viewport{flex:1;position:relative;overflow:hidden;touch-action:none;}
  #view{position:absolute;top:0;left:0;transform-origin:0 0;will-change:transform;}
  #pageImg{display:block;width:auto;height:auto;max-width:none;-webkit-user-select:none;user-select:none;pointer-events:none;}
  #markers{position:absolute;inset:0;}
  :root{--marker-size:84px;--marker-font-size:30px;--marker-visual-scale:1;}
  .mk{position:absolute;transform:translate(-50%,-50%) scale(var(--marker-visual-scale));transform-origin:center center;min-width:var(--marker-size);height:var(--marker-size);padding:0 calc(var(--marker-size) * 0.18);border-radius:calc(var(--marker-size) / 2);display:flex;align-items:center;justify-content:center;gap:calc(var(--marker-size) * 0.12);color:#fff;font-size:var(--marker-font-size);font-weight:700;border:2.5px solid rgba(255,255,255,.85);box-shadow:0 3px 12px rgba(0,0,0,.4);cursor:pointer;z-index:5;line-height:1;}
  .mk.in{background:rgba(233,69,96,.66);}
  .mk.out{background:rgba(56,116,255,.66);}
  .mk.sel{outline:3px solid #ffd;outline-offset:2px;}
  .mk.drag{outline:3px solid #ffd;outline-offset:2px;cursor:grab;z-index:6;}
  .mk .cnt{font-size:calc(var(--marker-size) * 0.31);font-weight:600;background:rgba(0,0,0,.3);border-radius:999px;padding:1px 6px;min-width:calc(var(--marker-size) * 0.56);text-align:center;}
  .empty{position:absolute;left:50%;top:42%;transform:translateX(-50%);color:rgba(255,255,255,.55);font-size:15px;background:rgba(0,0,0,.35);padding:10px 16px;border-radius:10px;white-space:nowrap;}
  #modePill{position:fixed;top:8px;right:14px;display:flex;background:rgba(10,12,22,.88);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.16);border-radius:999px;padding:3px;z-index:55;box-shadow:0 6px 20px rgba(0,0,0,.45);}
  #modePill button{border:none;background:transparent;color:#8a9;font-size:13px;font-weight:800;padding:8px 16px;border-radius:999px;cursor:pointer;white-space:nowrap;}
  #modePill button.on{background:rgba(233,69,96,.85);color:#fff;}
  #modePill button:active{opacity:.85;}
  #rail{width:118px;flex:0 0 auto;background:rgba(16,18,30,.92);border-right:1px solid rgba(255,255,255,.09);overflow-y:auto;padding:10px 8px;flex-direction:column;gap:10px;z-index:20;}
  #rail.hidden{width:0;padding:0;border:none;overflow:hidden;}
  #rail .pthumb{position:relative;cursor:pointer;border-radius:10px;border:2px solid rgba(255,255,255,.12);overflow:hidden;flex:0 0 auto;}
  #rail .pthumb img{display:block;width:100%;height:auto;background:#222;}
  #rail .pthumb .pname{position:absolute;left:4px;bottom:4px;font-size:10px;color:#fff;background:rgba(0,0,0,.55);padding:2px 6px;border-radius:6px;}
  #rail .pthumb.active{border-color:#e94560;box-shadow:0 0 0 2px rgba(233,69,96,.35);}
  #toolbar{height:54px;flex:0 0 auto;align-items:center;gap:8px;padding:0 10px;background:rgba(16,18,30,.92);border-bottom:1px solid rgba(255,255,255,.09);z-index:20;}
  #toolbar .tbtn{border:none;border-radius:11px;background:rgba(255,255,255,.08);color:#fff;font-size:14px;font-weight:700;cursor:pointer;padding:8px 12px;min-height:38px;display:flex;align-items:center;gap:5px;}
  #toolbar .tbtn:active{transform:scale(.95);}
  #toolbar .tbtn.active{background:rgba(81,119,255,.5);}
  #toolbar .tbtn small{font-size:11px;color:#9ab;}
  #panel{width:min(300px,34vw);flex:0 0 auto;background:rgba(16,18,30,.92);border-left:1px solid rgba(255,255,255,.09);flex-direction:column;z-index:20;}
  #panel .ph{height:54px;flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;padding:0 14px;color:#e94560;font-weight:800;font-size:14px;border-bottom:1px solid rgba(255,255,255,.09);}
  #panel .ph .n{color:#9ab;font-weight:600;}
  #list{flex:1;overflow-y:auto;touch-action:pan-y;padding:8px;}
  .row{display:flex;align-items:center;gap:9px;padding:10px;border-radius:11px;background:rgba(255,255,255,.05);margin-bottom:7px;cursor:pointer;border:1.5px solid transparent;}
  .row.sel{border-color:#e94560;background:rgba(233,69,96,.14);}
  .row .rid{flex:0 0 auto;width:32px;height:32px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;color:#fff;}
  .row .rid.in{background:rgba(233,69,96,.75);}
  .row .rid.out{background:rgba(56,116,255,.75);}
  .row .rbody{flex:1;min-width:0;}
  .row .rtxt{font-size:13.5px;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .row .rtxt .ph2{color:#556;}
  .row .rmeta{font-size:11px;color:#8a9;margin-top:3px;}
  .row .rlen{flex:0 0 auto;background:rgba(0,0,0,.35);color:#ffd;font-size:12px;font-weight:700;padding:3px 8px;border-radius:999px;}
  #labelChrome{position:absolute;inset:0;pointer-events:none;z-index:1;}
  .island{position:fixed;background:rgba(15,17,33,.92);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.16);border-radius:14px;padding:5px;box-shadow:0 8px 22px rgba(0,0,0,.55);z-index:40;pointer-events:auto;}
  .island .grip{width:22px;height:4px;border-radius:2px;background:rgba(255,255,255,.24);cursor:grab;margin:0 auto 3px;flex:0 0 auto;}
  .island .btns{display:flex;flex-direction:column;gap:4px;}
  .island.h .btns{flex-direction:row;}
  .island button{border:none;border-radius:9px;background:rgba(255,255,255,.09);color:#fff;font-size:15px;font-weight:800;cursor:pointer;padding:7px 10px;min-height:36px;min-width:40px;}
  .island button:active{transform:scale(.93);} .island button.primary{background:rgba(233,69,96,.82);} .island button.blue{background:rgba(81,119,255,.45);} .island button.sm{font-size:12px;padding:5px 7px;min-width:32px;}
  .island button.cq{font-size:11px;padding:4px 6px;min-width:38px;flex:1;}
  .island button.cq.active{background:rgba(233,69,96,.85);color:#fff;}
  .island .lbl{font-size:11px;color:#ffd;font-weight:800;text-align:center;padding:0 4px;align-self:center;}
  .island .lbl small{display:block;color:#8a9;font-weight:600;font-size:8px;text-align:center;}
  #iAdd button{padding:10px 7px;min-height:44px;min-width:34px;font-size:16px;}
  #iAdd .lbl{font-size:10px;max-width:60px;line-height:1.2;}
  #iAdd .lbl small{font-size:8px;}
  #iMenu{top:50%;right:5px;transform:translateY(-50%);}
  #topNav{position:absolute;inset:0;pointer-events:none;z-index:1;display:none;}
  body.label #topNav,body.editing #topNav{display:block;}
  #editor{position:fixed;left:0;right:0;bottom:10px;background:rgba(14,16,30,.97);border-top:2px solid rgba(233,69,96,.75);padding:10px 14px calc(12px + env(safe-area-inset-bottom,0px));z-index:70;display:none;box-shadow:0 -12px 34px rgba(0,0,0,.55);}
  #editor .e-top{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;}
  #editor .e-id{color:#e94560;font-weight:800;font-size:14px;}
  #editor .badge{font-size:12px;padding:3px 9px;border-radius:999px;color:#fff;}
  #editor .badge.in{background:rgba(233,69,96,.7);}
  #editor .badge.out{background:rgba(56,116,255,.7);}
  #editor .e-coord{color:#ffd;font-size:11px;font-family:monospace;}
  #editor .e-count{color:#9aa;font-size:12px;margin-left:auto;white-space:nowrap;}
  #editor #symBtn{font-size:15px;padding:2px 8px;border-radius:999px;border:1px solid #3c3c54;background:rgba(255,255,255,.06);color:#ccc;cursor:pointer;}
  #editor #symBtn:hover,#editor #symBtn.on{background:rgba(233,69,96,.3);border-color:#e94560;color:#fff;}
  #symPicker{display:none;position:fixed;z-index:9999;background:#1a1a2e;border:1.5px solid #3c3c54;border-radius:16px;padding:8px 6px;box-shadow:0 12px 36px rgba(0,0,0,.6);max-width:min(340px,96vw);}
  #symPicker.show{display:flex;flex-wrap:wrap;gap:4px;justify-content:center;}
  #symPicker button{width:40px;height:40px;border-radius:10px;border:1px solid transparent;background:rgba(255,255,255,.04);color:#ddd;font-size:19px;cursor:pointer;display:flex;align-items:center;justify-content:center;touch-action:manipulation;}
  #symPicker button:active,#symPicker button:hover{background:rgba(233,69,96,.25);border-color:#e94560;}
  #editor textarea{width:100%;min-height:52px;max-height:34vh;padding:11px 13px;font-size:17px;border-radius:14px;border:2px solid #2c2c44;background:rgba(0,0,0,.4);color:#fff;resize:none;font-family:inherit;-webkit-user-select:text;user-select:text;touch-action:auto;line-height:1.45;}
  #editor textarea:focus{outline:none;border-color:#e94560;}
  #editor .e-act{display:flex;gap:8px;margin-top:9px;}
  #editor .e-act button{flex:1;border:none;border-radius:12px;padding:10px 4px;font-size:17px;font-weight:800;cursor:pointer;color:#fff;background:rgba(255,255,255,.09);min-height:42px;}
  #editor .e-act button.primary{background:rgba(233,69,96,.82);}
  #editor .e-hint{font-size:11px;color:#667;text-align:center;margin-top:6px;padding-bottom:2px;}
  #radial{position:fixed;background:rgba(12,14,26,.96);border:1px solid rgba(255,255,255,.16);border-radius:14px;padding:6px;display:none;flex-direction:column;gap:4px;z-index:80;box-shadow:0 14px 40px rgba(0,0,0,.5);min-width:156px;}
  #radial button{border:none;border-radius:9px;padding:13px 14px;text-align:left;background:rgba(255,255,255,.07);color:#fff;font-size:14px;cursor:pointer;font-weight:600;}
  #radial button:active{background:rgba(233,69,96,.35);} #radial button.warn{color:#ff9d9d;}
  #pgModal{position:fixed;inset:0;background:rgba(6,7,12,.7);display:none;z-index:65;align-items:center;justify-content:center;}
  #pgModal .grid{width:min(620px,92vw);max-height:70vh;overflow:auto;background:rgba(15,17,33,.97);border:1px solid rgba(255,255,255,.14);border-radius:18px;padding:14px;display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:10px;}
  #pgModal .pthumb{position:relative;cursor:pointer;border-radius:10px;border:2px solid rgba(255,255,255,.12);overflow:hidden;}
  #pgModal .pthumb.active{border-color:#e94560;}
  #pgModal .pthumb img{display:block;width:100%;height:auto;background:#222;}
  #pgModal .pthumb .pname{position:absolute;left:4px;bottom:4px;font-size:10px;color:#fff;background:rgba(0,0,0,.55);padding:2px 6px;border-radius:6px;}
  #pgModal .close{margin-top:12px;width:100%;padding:12px;border:none;border-radius:12px;background:#e94560;color:#fff;font-size:15px;font-weight:800;cursor:pointer;}
  #hint{position:fixed;inset:0;background:rgba(6,7,12,.82);backdrop-filter:blur(8px);display:none;z-index:90;align-items:center;justify-content:center;}
  #hint .box{width:min(440px,90vw);max-height:86vh;overflow:auto;background:#151826;border:1px solid rgba(255,255,255,.14);border-radius:18px;padding:24px;}
  #hint h2{color:#e94560;font-size:19px;margin-bottom:14px;}
  #hint ul{list-style:none;}
  #hint li{padding:9px 0;border-bottom:1px dashed rgba(255,255,255,.08);font-size:14px;color:#dde;display:flex;align-items:center;gap:12px;}
  #hint li .g{flex:0 0 auto;min-width:96px;text-align:center;background:rgba(233,69,96,.18);border:1px solid rgba(233,69,96,.4);color:#ffb3c0;border-radius:8px;font-size:12px;padding:4px 6px;font-weight:700;}
  #hint .close{margin-top:18px;width:100%;padding:13px;border:none;border-radius:12px;background:#e94560;color:#fff;font-size:16px;font-weight:800;cursor:pointer;}
  body.dim .island,body.dim #modePill{opacity:0.22;transition:opacity 0.3s ease;}
  body.dim .island:hover,body.dim .island:active{opacity:1;}
  body.dim #bDim{opacity:0.7;}
  #rail,#toolbar,#panel,#labelChrome{display:none;}
  body.label #labelChrome{display:block;animation:fadeIn .15s ease;}
  body.input #rail,body.input #panel{display:flex;animation:fadeIn .15s ease;}
  body.input #toolbar{display:flex;animation:fadeIn .15s ease;}
  body.editing #iAdd,body.editing #iZoom,body.editing #rail,body.editing #toolbar,body.editing #panel{display:none !important;}
</style>
</head>
<body oncontextmenu="return false">
  <div id="modePill">
    <button id="mLabel" class="on">🏷 標號</button>
    <button id="mInput">✎ 輸入</button>
  </div>
  <div id="app">
    <div id="rail"></div>
    <div id="center">
      <div id="toolbar">
        <button class="tbtn" id="bRail" title="收合/展開左欄">☰</button>
        <div style="flex:1"></div>
        <button class="tbtn" id="bAddI">＋<small id="bAddILbl">放置·框內</small></button>
        <button class="tbtn" id="bInOutI">內</button>
        <button class="tbtn" id="bZOut">－</button>
        <button class="tbtn" id="bZIn">＋</button>
        <button class="tbtn" id="bQuality">質量</button>
        <button class="tbtn" id="bRetest" title="重測網速">重測</button>
        <button class="tbtn" id="bMarkerDec" title="縮小標號">−</button>
        <button class="tbtn" id="bMarkerInc" title="放大標號">＋</button>
        <button class="tbtn" id="bHelp">?</button>
      </div>
      <div id="viewport">
        <div id="view">
          <img id="pageImg" alt="">
          <div id="markers"></div>
        </div>
      </div>
    </div>
    <div id="panel">
      <div class="ph">📋 標號清單 <span class="n" id="listCount">0</span></div>
      <div id="list"></div>
    </div>
  </div>
  <div id="topNav">
    <div class="island h" id="iNav" style="top:5px;left:5px;">
      <div class="grip"></div>
      <div class="btns">
        <button onclick="flip(-1)">◀</button>
        <div class="lbl" id="navLbl">1/0</div>
        <button onclick="flip(1)">▶</button>
      </div>
    </div>
  </div>
  <div id="labelChrome">
    <div class="island" id="iMenu">
      <div class="grip"></div>
      <div class="btns">
        <button onclick="openPgModal()">☰</button>
        <button class="sm" id="bDim" onclick="toggleDim()">◐</button>
        <button class="sm" onclick="openHint()">?</button>
        <button class="sm" id="bMarkerToggle" title="標號大小">🔧</button>
      </div>
    </div>
    <div class="island" id="iAdd" style="left:14px;bottom:16px;">
      <div class="grip"></div>
      <div class="btns">
        <button class="primary" id="bAdd">＋</button>
        <button class="blue" id="bInOut">內</button>
        <div class="lbl" id="addLbl"><small>新增標號 · 框內</small></div>
      </div>
    </div>
    <div class="island" id="iZoom" style="right:14px;bottom:16px;">
      <div class="grip"></div>
      <div class="btns">
        <button onclick="zoomStep(1.4)">＋</button>
        <button class="sm" onclick="fitView()">100%</button>
        <button onclick="zoomStep(1/1.4)">－</button>
      </div>
    </div>
    <div class="island" id="markerIsland" style="right:80px;top:50%;transform:translateY(-50%);display:none;">
      <div class="grip"></div>
      <div style="padding:8px;display:flex;flex-direction:column;gap:8px;min-width:160px;">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
          <button id="mDec" class="sm">−</button>
          <button id="mInc" class="sm">＋</button>
        </div>
        <input id="markerRange" type="range" min="0" max="1000" step="1" style="width:100%">
        <div style="display:flex;align-items:center;gap:4px;border-top:1px dashed rgba(255,255,255,.15);padding-top:8px;">
          <span class="lbl" style="font-size:9px;">畫質<br><small>緩存</small></span>
          <button class="sm cq" data-q="low" onclick="setQuality('low')">1000</button>
          <button class="sm cq" data-q="med" onclick="setQuality('med')">2000</button>
          <button class="sm cq" data-q="orig" onclick="setQuality('orig')">原圖</button>
        </div>
      </div>
    </div>
  </div>
  <div id="radial"></div>
  <div id="editor">
    <div class="e-top">
      <span class="e-id">標號 #<span id="eId">0</span></span>
      <span class="badge in" id="eBadge">框內</span>
      <span class="e-coord" id="eCoord">0.00,0.00</span>
      <button id="symBtn" title="特殊符號">Ω</button>
      <span class="e-count" id="eCount">0 字</span>
    </div>
    <textarea id="eText" placeholder="輸入翻譯文字…"></textarea>
    <div class="e-act">
      <button id="ePrev" title="上一顆">▲</button>
      <button id="eToggle" title="切換內外">↕</button>
      <button class="primary" id="eSave" title="保存">💾</button>
      <button id="eNext" title="下一顆">▼</button>
      <button id="eClose">✖</button>
    </div>
  </div>
  <div id="symPicker"></div>
  <div id="pgModal">
    <div style="width:min(640px,94vw);max-height:80vh;display:flex;flex-direction:column;">
      <div class="grid" id="pgGrid"></div>
      <button class="close" onclick="closePgModal()">關閉</button>
    </div>
  </div>
  <div id="hint">
    <div class="box">
      <h2>漫畫標號器</h2>
      <ul>
        <li><span class="g">🏷 標號</span>浮島模式：畫布全空，四顆浮島放標號</li>
        <li><span class="g">✎ 輸入</span>雙欄模式：左縮圖、右清單、中央畫布</li>
        <li><span class="g">點氣球</span>輸入欄從底部彈出，圖片仍可自由拖動縮放</li>
        <li><span class="g">長按空白</span>兩模式都可直接新增標號</li>
        <li><span class="g">兩指縮放</span>放大 / 縮小 · 單指拖動平移</li>
        <li><span class="g">雙擊</span>適合視窗 ⇄ 放大</li>
        <li><span class="g">切換</span>標號⇄輸入時，頁面 / 縮放 / 選中標號都保留</li>
      </ul>
      <div style="border-top:1px dashed rgba(255,255,255,.15);margin:14px 0 10px;color:#e94560;font-weight:800;font-size:14px;">💻 電腦快捷鍵</div>
      <ul>
        <li><span class="g">滾輪</span>上下滾動圖片</li>
        <li><span class="g">Ctrl＋[ / ]</span>縮小 / 放大 · <span class="g">0</span>適合視窗</li>
        <li><span class="g">← →</span>翻頁</li>
        <li><span class="g">↑ ↓</span>切換標號 · <span class="g">Ctrl＋↑↓</span>編輯中切換</li>
        <li><span class="g">Ctrl＋Enter</span>保存 · <span class="g">Esc</span>關閉</li>
        <li><span class="g">右鍵</span>＝長按選單（空白可新增）</li>
      </ul>
      <button class="close" onclick="closeHint()">開始使用</button>
    </div>
  </div>
<script>
const images = {{ images|tojson }};
const INIT_MODE = {{ mode|tojson }};
const INIT_IMG = {{ initial_img|tojson }};
const INIT_DPI = {{ initial_dpi|tojson }};
const INIT_SCALE = {{ initial_scale|tojson }};
// image quality selection (stored in localStorage)
const QUALITY_MAP = {low:1000, med:2000, orig:'orig'};
let quality = localStorage.getItem('img_quality') || 'med';
let preferred_scale = localStorage.getItem('preferred_scale') || (INIT_SCALE||null);
// marker size in pixels (primary). null means use legacy markerScale multiplier.
let markerScale = 0.66; // legacy multiplier fallback
let markerPx = null; // explicit pixel size

function computeBaseMarkerSize(){ const base = Math.min(vw(), vh()); return clamp(84 + base * 0.09, 84, 168); }
// marker size is perceptual (pixel size): use a log/geometric slider so equal drag = equal ratio change (15→30 = 2x, 60 = 4x)
const SIZE_MIN = 6, SIZE_MAX = 500, SIZE_LOG_RATIO = Math.log(SIZE_MAX / SIZE_MIN);
function sizeToSlider(px){ return Math.log(px / SIZE_MIN) / SIZE_LOG_RATIO; } // 0..1 (left half covers small sizes)
function sliderToSize(t){ return SIZE_MIN * Math.exp(t * SIZE_LOG_RATIO); }    // SIZE_MIN..SIZE_MAX

function setMarkerPx(px, persist=true){
  markerPx = Math.max(4, Math.min(2000, Number(px)));
  updateMarkerScale();
  renderMarkers();
  if(persist){
    fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({marker_px: markerPx})}).then(r=>r.json()).catch(()=>{});
  }
}

// update UI elements for marker px (label + range)
function refreshMarkerUi(){
  try{ if(markerPx!=null) document.getElementById('markerRange').value = Math.round(sizeToSlider(markerPx)*1000); }catch(_){ }
}

function setMarkerScale(s, persist=true){
  markerScale = Math.max(0.2, Math.min(3.0, Number(s)));
  // switching to scale mode clears explicit px
  markerPx = null;
  updateMarkerScale();
  renderMarkers();
  if(persist){
    fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({marker_scale: markerScale})}).then(r=>r.json()).catch(()=>{});
  }
}

// speed re-test interval (days)
const SPEED_RETEST_DAYS = 7;

function refreshQualityButtons(){ try{ document.querySelectorAll('button.cq').forEach(b=>b.classList.toggle('active', b.dataset.q===quality)); }catch(_){ } }
function setQuality(q){ quality = q; localStorage.setItem('img_quality', q); const b=document.getElementById('bQuality'); if(b) b.textContent=q; refreshQualityButtons(); loadPage(); }
function setPreferredScale(s){ preferred_scale = s; localStorage.setItem('preferred_scale', s); }
function getImageUrl(name){ if(!name) return '/image/'+encodeURIComponent(name); if(quality==='orig') return '/image/'+encodeURIComponent(name); return '/image_variant/'+QUALITY_MAP[quality]+'/'+encodeURIComponent(name); }
function runSpeedTestOnce(force=false){
  const last = localStorage.getItem('net_speed_last');
  if(!force && last){
    try{
      const lastTs = Number(last);
      const days = (Date.now()-lastTs)/(1000*60*60*24);
      if(days < SPEED_RETEST_DAYS && localStorage.getItem('net_speed_kbps')) return;
    }catch(_){ }
  }
  const t0=performance.now();
  fetch('/api/speed_test?rand='+Math.random()).then(r=>r.blob()).then(b=>{
    const t1=performance.now(); const kb=b.size/1024; const sec=Math.max(0.001,(t1-t0)/1000); const kbps=kb/sec;
    localStorage.setItem('net_speed_kbps', kbps);
    localStorage.setItem('net_speed_last', String(Date.now()));
    if(kbps<1000) setQuality('low'); else if(kbps<5000) setQuality('med'); else setQuality('orig');
  }).catch(()=>{});
}
// 設定初始模式
document.body.classList.add(INIT_MODE==='input'?'input':'label');
if(INIT_MODE==='input'){
  document.getElementById('mInput').classList.add('on');
  document.getElementById('mLabel').classList.remove('on');
}
// 自動替換輸入字符
const CHAR_MAP = {'⋯':'…','@':'♪','...':'…','¥':'❤','€':'♥','*':'♡','～':'~'};
let mode='label', cur=0, scale=1, tx=0, ty=0;
let imgW=0, imgH=0;
let markers=[];
let selId=null;
let curM=null, editorOpen=false, dirty=false;
let placing=false, placeInside=1;
let dragMk=null; // marker id currently in free-drag mode
let kbH=0;
const MIN=0.2, MAX=6;
const viewport=document.getElementById('viewport');
const view=document.getElementById('view');
const img=document.getElementById('pageImg');
function clamp(v,min,max){ return Math.min(max, Math.max(min, v)); }
function updateMarkerScale(){
  const base = Math.min(vw(), vh());
  const baseSize = clamp(84 + base * 0.09, 84, 168);
  const size = markerPx!=null ? markerPx : (baseSize * markerScale);
  const visualScale = scale > 0 ? Math.max(0.8, Math.min(1.6, 1 / Math.max(scale, 0.7))) : 1;
  const fontSize = Math.max(11, size * 0.34);
  document.documentElement.style.setProperty('--marker-size', `${size}px`);
  document.documentElement.style.setProperty('--marker-font-size', `${fontSize}px`);
  document.documentElement.style.setProperty('--marker-visual-scale', `${visualScale}`);
  try{
    document.querySelectorAll('.mk').forEach(el=>{
      el.style.minWidth = `${size}px`;
      el.style.height = `${size}px`;
      el.style.fontSize = `${Math.max(12, Math.round(fontSize))}px`;
      const cnt = el.querySelector('.cnt');
      if(cnt){ cnt.style.fontSize = `${Math.max(10, Math.round(size*0.31))}px`; }
      el.style.transform = `translate(-50%,-50%) scale(${visualScale})`;
    });
  }catch(_){ }
}
const markersDiv=document.getElementById('markers');
const editor=document.getElementById('editor');
const ta=document.getElementById('eText');
const vv=window.visualViewport;
function vw(){ return vv?vv.width:window.innerWidth; }
function vh(){ return vv?vv.height:window.innerHeight; }
function vtop(){ return vv?vv.offsetTop:0; }
function barHeight(){ return editorOpen?editor.offsetHeight:64; }
function visibleArea(){
  const top=vtop();
  let h=vh();
  if(editorOpen){ h=Math.max(140, h-barHeight()-10); }
  return {w:vw(), h:h, top:top};
}
function updateKb(){
  kbH = vv?Math.max(0, window.innerHeight - vv.height):0;
  editor.style.bottom=(kbH+10)+'px';
  if(editorOpen && curM){ setTimeout(()=>aimMarker(curM),0); }
}
if(vv){ vv.addEventListener('resize', updateKb); }
function apply(){ view.style.transform=`translate(${tx}px, ${ty}px) scale(${scale})`; updateMarkerScale(); }
function fitView(){
  if(!imgW) return;
  const a=visibleArea();
  scale=Math.min(a.w/imgW, a.h/imgH)*0.985;
  tx=(a.w-imgW*scale)/2; ty=(a.h-imgH*scale)/2; apply();
  // save precise scale after fitting
  persistScale();
}
function clampPan(){
  if(!imgW) return;
  const a=visibleArea();
  const iw=imgW*scale, ih=imgH*scale;
  tx = iw<=a.w ? (a.w-iw)/2 : Math.max(a.w-iw, Math.min(0,tx));
  ty = ih<=a.h ? (a.top+(a.h-ih)/2) : Math.max(a.top+a.h-ih, Math.min(a.top,ty));
  apply();
}
function zoomAt(px,py,f){
  const vx=(px-tx)/scale, vy=(py-ty)/scale;
  const ns=Math.max(MIN,Math.min(MAX,scale*f));
  tx=px-vx*ns; ty=py-vy*ns; scale=ns; clampPan();
  // persist precise scale after any programmatic zoom
  persistScale();
}

// persist precise scale
function persistScale(){
  try{ setPreferredScale(Number(scale).toFixed(3)); }catch(_){ }
}
function zoomStep(f){ zoomAt(vw()/2, vtop()+vh()/2, f); }
function aimMarker(m){
  if(!imgW) return;
  const a=visibleArea();
  const cx=a.w/2, cy=a.top+a.h/2;
  const fitS=Math.min(a.w/imgW, a.h/imgH);
  scale=Math.max(scale, Math.min(MAX, fitS*1.6));
  tx=cx-m.x*imgW*scale; ty=cy-m.y*imgH*scale;
  clampPan();
}
function focusMarker(m){
  const a=visibleArea();
  scale=Math.max(scale, Math.min(a.w/imgW,a.h/imgH)*1.6);
  tx=a.w/2-m.x*imgW*scale; ty=a.h/2-m.y*imgH*scale; clampPan();
}
function fmtLen(t){ if(!t) return 0; let n=0; for(const ch of t){ if(/\s/.test(ch))continue; n+=ch.charCodeAt(0)<=127?0.5:1; } n=Math.round(n*10)/10; return Number.isInteger(n)?n:n.toFixed(1); }
function applyChars(t){ if(!t) return t; let r=t; Object.keys(CHAR_MAP).sort((a,b)=>b.length-a.length).forEach(k=>{ r=r.split(k).join(CHAR_MAP[k]); }); return r; }
function curMarkers(){ return markers; }
function markerAt(sx,sy){
  if(!imgW) return null;
  return markers.find(m=>{
    const mx=tx+m.x*imgW*scale, my=ty+m.y*imgH*scale;
    return Math.hypot(sx-mx,sy-my)<=32;
  })||null;
}
function setSel(id){ selId=id; document.querySelectorAll('.mk').forEach(el=>el.classList.toggle('sel',Number(el.dataset.id)===id)); renderList(); }
function renderMarkers(){
  markersDiv.innerHTML='';
  if(!images.length){ markersDiv.innerHTML='<div class="empty">⚠️ 沒有找到圖片，請檢查 TXT 檔和圖片目錄</div>'; return; }
  if(!markers.length){ markersDiv.innerHTML='<div class="empty">📭 此頁尚無標號 · 長按空白或按「＋」新增</div>'; renderList(); return; }
  markers.slice().sort((a,b)=>a.id-b.id).forEach(m=>{
    const el=document.createElement('div');
    el.className='mk '+(m.inside===1?'in':'out');
    el.dataset.id=m.id;
    if(m.id===selId) el.classList.add('sel');
    if(dragMk===m.id) el.classList.add('drag');
    el.style.left=(m.x*100)+'%'; el.style.top=(m.y*100)+'%';
    el.innerHTML=`<span>${m.id}</span><span class="cnt">${fmtLen(m.text)}</span>`;
    el.addEventListener('pointerdown',e=>{
      if(e.button && e.button!==0) return; // ignore right/middle click
      e.stopPropagation();
      if(dragMk===m.id){
        e.preventDefault();
        try{ el.setPointerCapture(e.pointerId); }catch(_){ }
        m._drag=true; return;
      }
      m._m0={x:e.clientX,y:e.clientY}; m._pressed=true;
      m._lp=setTimeout(()=>{ m._lp=null; m._longPress=true; showRadial(e.clientX,e.clientY,markerItems(m)); },450);
    });
    el.addEventListener('pointermove',e=>{
      e.stopPropagation();
      if(m._drag){
        e.preventDefault();
        const r=view.getBoundingClientRect();
        if(r.width&&r.height){
          let x=(e.clientX-r.left)/r.width, y=(e.clientY-r.top)/r.height;
          x=Math.max(0,Math.min(1,x)); y=Math.max(0,Math.min(1,y));
          m.x=x; m.y=y;
          el.style.left=(x*100)+'%'; el.style.top=(y*100)+'%';
        }
        return;
      }
      if(m._m0&&Math.hypot(e.clientX-m._m0.x,e.clientY-m._m0.y)>9){ clearTimeout(m._lp); m._lp=null; }
    });
    el.addEventListener('pointerup',e=>{
      e.stopPropagation();
      if(m._drag){ m._drag=false; dragMk=null; persist(); renderMarkers(); return; }
      if(m._lp){ clearTimeout(m._lp); m._lp=null; }
      if(m._pressed&&!m._longPress){ setSel(m.id); openEditor(m); }
      m._pressed=false; m._longPress=false; m._m0=null;
    });
    markersDiv.appendChild(el);
  });
  renderList();
}
function renderList(){
  const list=document.getElementById('list');
  document.getElementById('listCount').textContent=markers.length;
  list.innerHTML='';
  if(!markers.length){ list.innerHTML='<div style="color:#667;text-align:center;padding:14px;">此頁沒有標號</div>'; return; }
  markers.slice().sort((a,b)=>a.id-b.id).forEach(m=>{
    const row=document.createElement('div');
    row.className='row'+(m.id===selId?' sel':'');
    const t=m.text||'';
    row.innerHTML=`<div class="rid ${m.inside===1?'in':'out'}">${m.id}</div>
      <div class="rbody"><div class="rtxt">${t?escapeHtml(t):'<span class="ph2">（空白）</span>'}</div>
      <div class="rmeta">${m.inside===1?'框內':'框外'}</div></div>
      <div class="rlen">${fmtLen(t)}</div>`;
    row.onclick=()=>{ setSel(m.id); focusMarker(m); openEditor(m); };
    list.appendChild(row);
  });
  const sr=list.querySelector('.row.sel');
  if(sr) sr.scrollIntoView({block:'nearest'});
}
function escapeHtml(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function addMarkerAt(px,py,inside){
  const r=view.getBoundingClientRect();
  if(!r.width||!r.height) return;
  let x=(px-r.left)/r.width, y=(py-r.top)/r.height;
  x=Math.max(0,Math.min(1,x)); y=Math.max(0,Math.min(1,y));
  const id=(markers.length?Math.max(...markers.map(m=>m.id)):0)+1;
  markers.push({id,x,y,inside,text:''});
  setSel(id); renderMarkers(); persist();
}
function buildRail(){
  const rail=document.getElementById('rail');
  rail.innerHTML='';
  images.forEach((name,i)=>{
    const d=document.createElement('div');
    d.className='pthumb'+(i===cur?' active':'');
    const im=document.createElement('img');
    im.src=getImageUrl(name); im.loading='lazy';
    d.appendChild(im);
    const n=document.createElement('div'); n.className='pname'; n.textContent=name; d.appendChild(n);
    d.onclick=()=>{ changePage(i, false); };
    rail.appendChild(d);
  });
}
const radial=document.getElementById('radial');
function showRadial(x,y,items){
  radial.innerHTML='';
  items.forEach(it=>{ const b=document.createElement('button'); b.textContent=it.label; if(it.warn)b.className='warn'; b.onclick=()=>{ radial.style.display='none'; it.run(); }; radial.appendChild(b); });
  radial.style.display='flex';
  const rw=radial.offsetWidth||156, rh=radial.offsetHeight||120;
  radial.style.left=Math.min(window.innerWidth-rw-10, Math.max(10,x+6))+'px';
  radial.style.top=Math.min(window.innerHeight-rh-10, Math.max(10,y+6))+'px';
}
function startDragMarker(m){
  if(editorOpen){ closeEditor(); }
  setSel(m.id);
  if(imgW){
    const mx=tx+m.x*imgW*scale, my=ty+m.y*imgH*scale;
    zoomAt(mx, my, 2);
  }
  dragMk=m.id;
  renderMarkers();
}
function markerItems(m){ return [
  {label:'✏️ 編輯文字', run:()=>{ setSel(m.id); openEditor(m); }},
  {label:'✋ 拖曳位置', run:()=>{ startDragMarker(m); }},
  {label:m.inside===1?'↔ 切換為框外':'↔ 切換為框內', run:()=>{ m.inside=m.inside===1?2:1; renderMarkers(); persist(); }},
  {label:'🗑 刪除標號', warn:true, run:()=>{ const i=markers.indexOf(m); if(i>=0) markers.splice(i,1); if(curM===m) closeEditor(); renderMarkers(); persist(); }},
];}
function openEditor(m){
  if(editorOpen && curM && curM!==m){ persistText(); flush(); }
  curM=m; editorOpen=true; dirty=false;
  document.body.classList.add('editing');
  editor.style.display='block';
  fillEditor(m);
  updateKb();
  setTimeout(()=>{ aimMarker(m); },30);
  setTimeout(()=>ta.focus(),120);
}
function fillEditor(m){
  document.getElementById('eId').textContent=m.id;
  const b=document.getElementById('eBadge');
  b.textContent=m.inside===1?'框內':'框外';
  b.className='badge '+(m.inside===1?'in':'out');
  document.getElementById('eCoord').textContent=m.x.toFixed(2)+', '+m.y.toFixed(2);
  ta.value=m.text||'';
  ta.style.height='auto'; ta.style.height=Math.min(ta.scrollHeight,0.34*window.innerHeight)+'px';
  updateCount();
}
function updateCount(){ document.getElementById('eCount').textContent=fmtLen(ta.value)+' 字'; }
function persistText(){ if(!curM) return; curM.text=applyChars(ta.value); updateMarkerBadge(curM.id); }
function updateMarkerBadge(id){
  const el=document.querySelector(`.mk[data-id="${id}"] .cnt`);
  if(el) el.textContent=fmtLen(ta.value);
}
function persist(cb){
  fetch('/api/save_dialogues',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:images[cur],dialogues:markers})})
    .then(r=>r.json()).then(d=>{ if(d.status==='ok'){ if(cb)cb(); } else { alert('保存失敗: '+d.error); } })
    .catch(err=>alert('網路錯誤: '+err));
}
function flush(){ if(dirty){ dirty=false; persist(); } }
function switchEditorMarker(d){
  if(!curM || !markers.length) return;
  persistText(); flush();
  const ms=markers.slice().sort((a,b)=>a.id-b.id);
  const i=ms.findIndex(m=>m.id===curM.id);
  const next=ms[(i+d+ms.length)%ms.length];
  setSel(next.id);
  fillEditor(next);
  curM=next; dirty=false;
  updateKb(); ta.focus();
  setTimeout(()=>aimMarker(next),30);
}
function toggleEditorInside(){
  if(!curM) return;
  curM.inside=curM.inside===1?2:1; dirty=true;
  renderMarkers(); fillEditor(curM);
}
function saveEditor(){ persistText(); flush(); updateMarkerBadge(curM?curM.id:null); }
function closeEditor(){
  if(!editorOpen) return;
  persistText();
  flush();
  editor.style.display='none';
  editorOpen=false; curM=null; dirty=false;
  document.body.classList.remove('editing');
  renderMarkers();
}
ta.addEventListener('input',()=>{
  if(ta.dataset._mappingLock === '1') return;
  const v=applyChars(ta.value);
  if(v!==ta.value){ const p=ta.selectionStart; ta.value=v; try{ta.setSelectionRange(p,p);}catch(_){} }
  dirty=true;
  ta.style.height='auto'; ta.style.height=Math.min(ta.scrollHeight,0.34*window.innerHeight)+'px';
  updateCount();
  updateMarkerBadge(curM?curM.id:null);
});
// 攔截單字元插入：在原生插入前完成替換，避免行動瀏覽器重複寫入造成雙字符
ta.addEventListener('beforeinput', (e) => {
  if(!e || e.inputType !== 'insertText' || !e.data) return;
  if(!Object.prototype.hasOwnProperty.call(CHAR_MAP, e.data)) return;
  e.preventDefault();
  const start = ta.selectionStart, end = ta.selectionEnd;
  const mapped = CHAR_MAP[e.data];
  ta.value = ta.value.slice(0, start) + mapped + ta.value.slice(end);
  ta.setSelectionRange(start + mapped.length, start + mapped.length);
  ta.dispatchEvent(new Event('input'));
});
document.getElementById('eSave').onclick=saveEditor;
document.getElementById('eClose').onclick=closeEditor;
document.getElementById('eToggle').onclick=toggleEditorInside;
document.getElementById('ePrev').onclick=()=>switchEditorMarker(-1);
document.getElementById('eNext').onclick=()=>switchEditorMarker(1);
const SYMBOLS = ['♡','♥','❤','♪','♫','♯','★','☆','✦','✧','…','〜','✕','✓','☺','☹','◉','◎','●','○','◇','◆','□','■','△','▲','▽','▼','→','←','↑','↓','「','」','『','』','【','】','、','。'];
const symPicker = document.getElementById('symPicker');
const symBtn = document.getElementById('symBtn');
function buildSymPicker(){
  symPicker.innerHTML = '';
  SYMBOLS.forEach(s => {
    const b = document.createElement('button');
    b.textContent = s;
    b.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      insertSym(s);
    };
    symPicker.appendChild(b);
  });
}
buildSymPicker();
function insertSym(s){
  const start = ta.selectionStart, end = ta.selectionEnd;
  const v = ta.value;
  if(start > 0 && v[start-1] === '/'){
    ta.value = v.slice(0, start-1) + s + v.slice(end);
    ta.setSelectionRange(start-1 + s.length, start-1 + s.length);
  } else {
    ta.value = v.slice(0, start) + s + v.slice(end);
    ta.setSelectionRange(start + s.length, start + s.length);
  }
  ta.focus();
  ta.dispatchEvent(new Event('input'));
  positionSymPicker();
}
function positionSymPicker(){
  const r = ta.getBoundingClientRect();
  symPicker.style.left = Math.max(6, Math.min(window.innerWidth - symPicker.offsetWidth - 6, r.left)) + 'px';
  symPicker.style.bottom = (window.innerHeight - r.top + 8) + 'px';
}
function toggleSymPicker(){
  const show = !symPicker.classList.contains('show');
  if(show){ positionSymPicker(); symPicker.classList.add('show'); symBtn.classList.add('on'); }
  else { symPicker.classList.remove('show'); symBtn.classList.remove('on'); }
}
symBtn.onclick = (e) => { e.preventDefault(); toggleSymPicker(); };
ta.addEventListener('keydown', (e) => {
  if(e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey){
    const start = ta.selectionStart;
    if(start === 0 || /[\s\n]$/.test(ta.value.slice(0, start))){
      e.preventDefault();
      const v = ta.value, s = ta.selectionStart, en = ta.selectionEnd;
      ta.value = v.slice(0, s) + '/' + v.slice(en);
      ta.setSelectionRange(s + 1, s + 1);
      ta.dispatchEvent(new Event('input'));
      if(!symPicker.classList.contains('show')) toggleSymPicker();
    }
  }
  if(e.key === 'Escape' && symPicker.classList.contains('show')){
    symPicker.classList.remove('show'); symBtn.classList.remove('on');
  }
});
document.addEventListener('click', (e) => {
  if(symPicker.classList.contains('show') && !symPicker.contains(e.target) && e.target !== symBtn && e.target !== ta){
    symPicker.classList.remove('show'); symBtn.classList.remove('on');
  }
});
let dimmed = false;
function toggleDim(){
  dimmed = !dimmed;
  document.body.classList.toggle('dim', dimmed);
  document.getElementById('bDim').textContent = dimmed ? '◑' : '◐';
}
function setMode(m){
  if(m===mode) return;
  mode=m; updateURL();
  document.body.classList.toggle('label',m==='label');
  document.body.classList.toggle('input',m==='input');
  document.getElementById('mLabel').classList.toggle('on',m==='label');
  document.getElementById('mInput').classList.toggle('on',m==='input');
  const cx=vw()/2, cy=vtop()+vh()/2;
  const vx=(cx-tx)/scale, vy=(cy-ty)/scale;
  requestAnimationFrame(()=>{
    tx=cx-vx*scale; ty=cy-vy*scale; clampPan();
    if(m==='input'){ buildRail(); renderList(); }
    else { renderList(); }
  });
}
document.getElementById('mLabel').onclick=()=>setMode('label');
document.getElementById('mInput').onclick=()=>setMode('input');
function updateURL(){
  let url;
  const img = (images.length && cur>=0) ? '/'+encodeURIComponent(images[cur]) : '';
  if(mode==='input'){ url='/input'+img; }
  else { url='/mark'+img; }
  // append dpi info if present
  if(preferred_scale){ url += '/scale-'+preferred_scale; }
  history.replaceState(null,'',url);
}
if(INIT_IMG){
  const i=images.indexOf(INIT_IMG);
  if(i>=0){ cur=i; }
}
updateURL();
function makeDraggable(el){
  const grip=el.querySelector('.grip');
  grip.addEventListener('pointerdown',e=>{
    e.preventDefault();
    if(editorOpen) return;
    const sx=e.clientX,sy=e.clientY;
    const l=el.offsetLeft,t=el.offsetTop;
    function onMove(ev){
      const nl=Math.max(0,Math.min(window.innerWidth-el.offsetWidth,l+ev.clientX-sx));
      const nt=Math.max(0,Math.min(window.innerHeight-el.offsetHeight,t+ev.clientY-sy));
      el.style.left=nl+'px'; el.style.top=nt+'px';
    }
    function onUp(){ window.removeEventListener('pointermove',onMove); window.removeEventListener('pointerup',onUp); }
    window.addEventListener('pointermove',onMove);
    window.addEventListener('pointerup',onUp);
  });
}
['iNav','iMenu','iAdd','iZoom'].forEach(id=>makeDraggable(document.getElementById(id)));
const bAdd=document.getElementById('bAdd'), bInOut=document.getElementById('bInOut'), bAddI=document.getElementById('bAddI');
function setPlace(v){
  placing=v;
  bAdd.style.background=v?'rgba(81,119,255,.6)':'rgba(233,69,96,.82)';
  bAddI.classList.toggle('active',v);
}
function updateInOut(){
  const isIn=placeInside===1;
  bInOut.textContent=isIn?'內':'外';
  document.getElementById('bInOutI').textContent=isIn?'內':'外';
  document.getElementById('addLbl').innerHTML='<small>新增標號 · '+(isIn?'框內':'框外')+'</small>';
  document.getElementById('bAddILbl').textContent='放置·'+(isIn?'框內':'框外');
  bInOut.style.background=isIn?'rgba(233,69,96,.5)':'rgba(56,116,255,.5)';
  document.getElementById('bInOutI').style.background=isIn?'rgba(233,69,96,.4)':'rgba(56,116,255,.4)';
}
bAdd.onclick=()=>setPlace(!placing);
bInOut.onclick=()=>{ placeInside=placeInside===1?2:1; updateInOut(); };
bAddI.onclick=()=>setPlace(!placing);
document.getElementById('bInOutI').onclick=()=>{ placeInside=placeInside===1?2:1; updateInOut(); };
document.getElementById('bZIn').onclick=()=>zoomStep(1.35);
document.getElementById('bZOut').onclick=()=>zoomStep(1/1.35);
document.getElementById('bRail').onclick=()=>document.getElementById('rail').classList.toggle('hidden');
document.getElementById('bHelp').onclick=()=>openHint();
function openPgModal(){
  const grid=document.getElementById('pgGrid');
  grid.innerHTML='';
  images.forEach((name,i)=>{
    const d=document.createElement('div');
    d.className='pthumb'+(i===cur?' active':'');
    const im=document.createElement('img');
    im.src=getImageUrl(name); im.loading='lazy';
    d.appendChild(im);
    const n=document.createElement('div'); n.className='pname'; n.textContent=name; d.appendChild(n);
    d.onclick=()=>{ closePgModal(); changePage(i, false); };
    grid.appendChild(d);
  });
  document.getElementById('pgModal').style.display='flex';
}
function closePgModal(){ document.getElementById('pgModal').style.display='none'; }
let pointers=new Map(), gesture=null;
let downT=0,downX=0,downY=0,moved=false,lpTimer=null,lpFired=false,suppressTap=false,lastTap={x:0,y:0,t:0};
function armLP(e){
  clearTimeout(lpTimer); lpFired=false;
  lpTimer=setTimeout(()=>{
    if(editorOpen||!gesture||gesture.type!=='pan'||pointers.size!==1) return;
    lpFired=true; suppressTap=true; moved=true;
    const m=markerAt(downX,downY);
    if(m){ showRadial(downX,downY,markerItems(m)); }
    else { addMarkerAt(downX,downY,placeInside); }
  },450);
}
function disarmLP(){ clearTimeout(lpTimer); lpFired=false; }
viewport.addEventListener('pointerdown',e=>{
  if(e.target.closest('#radial')) return;
  if(e.button && e.button!==0) return;
  e.preventDefault();
  try{ viewport.setPointerCapture(e.pointerId); }catch(_){ }
  pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
  if(pointers.size===2){ disarmLP(); suppressTap=true; moved=true; const [a,b]=[...pointers.values()]; gesture={type:'pinch',d0:Math.hypot(a.x-b.x,a.y-b.y),s0:scale}; }
  else {
    gesture={type:'pan',sx:e.clientX,sy:e.clientY,stx:tx,sty:ty};
    downT=Date.now(); downX=e.clientX; downY=e.clientY; moved=false; suppressTap=false;
    if(!editorOpen) armLP(e);
  }
});
viewport.addEventListener('pointermove',e=>{
  if(!pointers.has(e.pointerId)) return;
  pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
  if(!gesture) return;
  if(gesture.type==='pinch'){
    const [a,b]=[...pointers.values()];
    const d=Math.hypot(a.x-b.x,a.y-b.y);
    const ns=Math.max(MIN,Math.min(MAX,gesture.s0*d/(gesture.d0||1)));
    const mx=(a.x+b.x)/2, my=(a.y+b.y)/2;
    const vx=(mx-tx)/scale, vy=(my-ty)/scale;
    tx=mx-vx*ns; ty=my-vy*ns; scale=ns; clampPan();
  }else{
    const dx=e.clientX-gesture.sx, dy=e.clientY-gesture.sy;
    if(!moved&&Math.hypot(dx,dy)>5){ moved=true; disarmLP(); }
    if(moved){ tx=gesture.stx+dx; ty=gesture.sty+dy; apply(); }
  }
});
window.addEventListener('pointerup',e=>onEnd(e));
window.addEventListener('pointercancel',e=>onEnd(e));
function onEnd(e){
  if(!pointers.has(e.pointerId)) return;
  const up={x:e.clientX,y:e.clientY};
  const wasPinch=gesture&&gesture.type==='pinch';
  pointers.delete(e.pointerId);
  if(pointers.size===0){
    clearTimeout(lpTimer);
    gesture=null; clampPan();
    if(wasPinch){ persistScale(); }
    if(!moved&&!suppressTap&&!lpFired){
      const m=markerAt(up.x,up.y);
      if(m){ setSel(m.id); openEditor(m); }
      else if(placing&&!editorOpen){ addMarkerAt(up.x,up.y,placeInside); }
      else if(dragMk){ dragMk=null; renderMarkers(); }
    }
    if(!moved&&!lpFired){
      const now=Date.now();
      if(now-lastTap.t<300&&Math.hypot(up.x-lastTap.x,up.y-lastTap.y)<48){ doDoubleTap(up.x,up.y); lastTap.t=0; }
      else lastTap={x:up.x,y:up.y,t:now};
    }
    suppressTap=false; moved=false;
  }else if(gesture&&gesture.type==='pan'){
    gesture={type:'pan',sx:up.x,sy:up.y,stx:tx,sty:ty};
  }
}
function doDoubleTap(x,y){
  const a=visibleArea();
  const atFit=Math.abs(scale-(Math.min(a.w/imgW,a.h/imgH)*0.985))<0.05;
  if(atFit){ zoomAt(x,y,2.2); } else { fitView(); }
}
viewport.addEventListener('wheel', function(e){
  // wheel: scroll image vertically
  e.preventDefault();
  if(!imgW) return;
  ty -= e.deltaY;
  clampPan();
}, {passive:false});
viewport.addEventListener('contextmenu', function(e){
  e.preventDefault();
  const m = markerAt(e.clientX, e.clientY);
  if(m){ showRadial(e.clientX, e.clientY, markerItems(m)); }
  else { showRadial(e.clientX, e.clientY, [
    {label:'🟥 新增「框內」標號', run:()=>addMarkerAt(e.clientX,e.clientY,1)},
    {label:'🟦 新增「框外」標號', run:()=>addMarkerAt(e.clientX,e.clientY,2)},
    {label:'取消', warn:true, run:()=>{}},
  ]); }
});
function navMarker(d){
  if(!markers.length) return;
  if(editorOpen){ switchEditorMarker(d); return; }
  const ms=markers.slice().sort((a,b)=>a.id-b.id);
  let i=ms.findIndex(m=>m.id===selId);
  if(i<0) i = d>0 ? -1 : 0;
  const next=ms[(i+d+ms.length)%ms.length];
  setSel(next.id); focusMarker(next);
}
document.addEventListener('keydown', function(e){
  if(e.key==='Enter' && (e.ctrlKey||e.metaKey)){
    if(editorOpen){ e.preventDefault(); saveEditor(); }
    return;
  }
  if(e.ctrlKey && (e.key==='ArrowUp'||e.key==='ArrowDown')){
    e.preventDefault();
    if(markers.length){ navMarker(e.key==='ArrowUp'?-1:1); }
    return;
  }
  if(e.key==='Escape'){
    if(editorOpen){ closeEditor(); }
    else if(dragMk){ dragMk=null; renderMarkers(); }
    else if(document.getElementById('pgModal').style.display==='flex'){ closePgModal(); }
    else if(document.getElementById('hint').style.display==='flex'){ closeHint(); }
    else if(radial.style.display==='flex'){ radial.style.display='none'; }
    return;
  }
  const tag=(document.activeElement&&document.activeElement.tagName.toLowerCase());
  if(tag==='textarea'||tag==='input'){
    if(e.key==='PageUp'||e.key==='PageDown'){ e.preventDefault(); flip(e.key==='PageUp'?-1:1); }
    else if((e.ctrlKey||e.metaKey) && e.key==='ArrowLeft'){ e.preventDefault(); flip(-1); }
    else if((e.ctrlKey||e.metaKey) && e.key==='ArrowRight'){ e.preventDefault(); flip(1); }
    return;
  }
  if(e.key==='ArrowLeft'){ flip(-1); }
  else if(e.key==='ArrowRight'){ flip(1); }
  else if(e.key==='ArrowUp'){ navMarker(-1); }
  else if(e.key==='ArrowDown'){ navMarker(1); }
  else if(e.key==='PageUp'){ flip(-1); }
  else if(e.key==='PageDown'){ flip(1); }
  else if(e.key==='Home'){ if(images.length){changePage(0, !!editorOpen);} }
  else if(e.key==='End'){ if(images.length){changePage(images.length-1, !!editorOpen);} }
  else if((e.ctrlKey||e.metaKey) && (e.key===']'||e.key==='】')){ zoomStep(1.35); }
  else if((e.ctrlKey||e.metaKey) && (e.key==='['||e.key==='【')){ zoomStep(1/1.35); }
  else if(e.key==='0'){ fitView(); }
});
function changePage(index, openFirstMarker=false){
  if(editorOpen && curM){ persistText(); flush(); }
  cur=index;
  updateURL();
  loadPage(openFirstMarker);
}
function flip(d){ if(!images.length) return; changePage((cur+d+images.length)%images.length, !!editorOpen); }
function loadPage(openFirstMarker=false){
  selId=null;
  if(!images.length){ markers=[]; renderMarkers(); return; }
  img.src=getImageUrl(images[cur]);
  fetch('/api/get_dialogues?img='+encodeURIComponent(images[cur]))
    .then(r=>r.json())
    .then(data=>{
      if(data.error){ markers=[]; renderMarkers(); }
      else { markers=data.dialogues||[]; renderMarkers(); }
      if(openFirstMarker && editorOpen && markers.length){
        const first=markers.slice().sort((a,b)=>a.id-b.id)[0];
        if(first){ setSel(first.id); openEditor(first); }
      }
    })
    .catch(()=>{ markers=[]; renderMarkers(); });
  document.getElementById('navLbl').innerHTML=(cur+1)+'/'+images.length;
  buildRail();
}
img.onload=()=>{ imgW=img.naturalWidth; imgH=img.naturalHeight; // clear retry flag
  try{ delete img.dataset._tried_orig; }catch(_){ }
  fitView(); if(preferred_scale){ try{ scale = Number(preferred_scale); }catch(_){ } clampPan(); apply(); } renderMarkers(); };
img.onerror=()=>{
  markersDiv.innerHTML='<div class="empty">❌ 圖片載入失敗，正在回退至原圖…</div>';
  try{
    const tried = img.dataset._tried_orig;
    if(!tried && img.src && img.src.indexOf('/image_variant/')!==-1){
      img.dataset._tried_orig = '1';
      const name = images[cur];
      // report to server
      fetch('/api/log',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({msg:'variant_load_failed',level:'warn',img:name,src:img.src})}).catch(()=>{});
      img.src = '/image/'+encodeURIComponent(name)+'?rand='+Math.random();
      return;
    }
  }catch(_){ }
  // final failure, log and show message
  try{ fetch('/api/log',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({msg:'image_load_failed',level:'error',img:images[cur],src:img.src})}).catch(()=>{}); }catch(_){ }
};
window.addEventListener('resize',()=>{ updateKb(); if(!editorOpen) fitView(); updateMarkerScale(); });
function closeHint(){ document.getElementById('hint').style.display='none'; }
function openHint(){ document.getElementById('hint').style.display='flex'; }
mode=INIT_MODE; document.getElementById(INIT_MODE==='input'?'mInput':'mLabel').classList.add('on');
// initialize quality button and speed test
const bq=document.getElementById('bQuality'); if(bq){ bq.textContent=quality; bq.onclick=()=>{ const opts=['low','med','orig']; const idx=(opts.indexOf(quality)+1)%opts.length; setQuality(opts[idx]); }; }
refreshQualityButtons();
const br=document.getElementById('bRetest'); if(br){ br.onclick=()=>{ br.textContent='測試中…'; runSpeedTestOnce(true); setTimeout(()=>{ br.textContent='重測'; },3000); }
}
// load server config for marker scale
fetch('/api/config').then(r=>r.json()).then(d=>{
  try{
    const cfg = d.config||{};
    if(typeof cfg.marker_px !== 'undefined'){
      setMarkerPx(cfg.marker_px, false);
    } else if(typeof cfg.marker_scale !== 'undefined'){
      setMarkerScale(cfg.marker_scale, false);
    } else {
      // default to 66% of base
      setMarkerScale(0.66, false);
    }
  }catch(_){ setMarkerScale(0.66, false); }
}).catch(()=>{ setMarkerScale(0.66, false); });
if(!localStorage.getItem('preferred_scale') && INIT_SCALE) { preferred_scale = INIT_SCALE; localStorage.setItem('preferred_scale', INIT_SCALE); }

// marker controls
const bDec=document.getElementById('bMarkerDec'); if(bDec){ bDec.onclick=()=>{
  if(markerPx==null){ setMarkerPx(computeBaseMarkerSize()*markerScale); }
  setMarkerPx(Math.max(4, markerPx - 4));
} }
const bInc=document.getElementById('bMarkerInc'); if(bInc){ bInc.onclick=()=>{
  if(markerPx==null){ setMarkerPx(computeBaseMarkerSize()*markerScale); }
  setMarkerPx(markerPx + 4);
} }
// marker island hooks
const bMarkerToggle = document.getElementById('bMarkerToggle'); if(bMarkerToggle){ bMarkerToggle.onclick=()=>{
  const isl = document.getElementById('markerIsland'); isl.style.display = (isl.style.display==='flex' || isl.style.display==='block') ? 'none' : 'block';
  if(isl.style.display!=='none'){ refreshMarkerUi(); }
} }
makeDraggable(document.getElementById('markerIsland'));
const mDec = document.getElementById('mDec'); if(mDec){ mDec.onclick=()=>{ if(markerPx==null){ setMarkerPx(computeBaseMarkerSize()*markerScale); } setMarkerPx(Math.max(SIZE_MIN, Math.round(markerPx/1.2))); refreshMarkerUi(); } }
const mInc = document.getElementById('mInc'); if(mInc){ mInc.onclick=()=>{ if(markerPx==null){ setMarkerPx(computeBaseMarkerSize()*markerScale); } setMarkerPx(Math.min(SIZE_MAX, Math.round(markerPx*1.2))); refreshMarkerUi(); } }
const mRange = document.getElementById('markerRange'); if(mRange){ mRange.oninput=(e)=>{ setMarkerPx(Math.round(sliderToSize(e.target.value/1000))); refreshMarkerUi(); } }
loadPage(); updateInOut(); updateKb(); updateURL(); runSpeedTestOnce();
</script>
</body>
</html>
"""


def start_background_tasks():
  """Start background threads (image variant prewarm). Called from main.py (after set_work_dir) or __main__."""
  def prewarm_cache():
    """Prewarm only the first PREWARM_COUNT images (sorted) and otherwise rely on on-demand generation."""
    if Image is None:
      return
    cd = get_comic_dir()
    try:
      files = [f for f in os.listdir(cd) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]
      files.sort()
      # limit to first N to reduce startup IO
      for f in files[:PREWARM_COUNT]:
        p = os.path.join(cd, f)
        try:
          with Image.open(p) as im:
            ow, oh = im.size
            if ow > 1000:
              generate_variant_if_needed(1000, f)
            if ow > 2000:
              generate_variant_if_needed(2000, f)
        except Exception:
          continue
    except Exception:
      pass

  try:
    t = threading.Thread(target=prewarm_cache, daemon=True)
    t.start()
  except Exception:
    pass


if __name__ == '__main__':
    from utils.network import get_local_ip
    local_ip = get_local_ip()
    print("=" * 60)
    print("Comic labeler started")
    print(f"TXT file: {os.path.abspath(get_txt_file())}")
    print(f"Image directory: {os.path.abspath(get_comic_dir())}")
    print("=" * 60)
    print("Open this URL on your phone/browser:")
    print(f"   http://{local_ip}:5000")
    print("=" * 60)
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    start_background_tasks()
    app.run(host='0.0.0.0', port=5000, debug=False)
