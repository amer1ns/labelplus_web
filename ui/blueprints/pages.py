from flask import Blueprint, redirect, render_template

from core.comic import get_txt_file, parse_all_comics

pages_bp = Blueprint('pages', __name__)


def _serve(mode='label', initial_img=None, initial_dpi=None, initial_scale=None):
  all_data = parse_all_comics(get_txt_file())
  images = list(all_data.keys())
  images.sort()
  return render_template('index.html', images=images, mode=mode, initial_img=initial_img, initial_dpi=initial_dpi, initial_scale=initial_scale)


def _parse_dpi_scale(img):
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
  return img, dpi, scale


@pages_bp.route('/')
def index():
    all_data = parse_all_comics(get_txt_file())
    images = list(all_data.keys())
    images.sort()
    if images:
        return redirect(f'/mark/{images[0]}')
    return _serve()


@pages_bp.route('/label')
def label_mode():
    return _serve('label')


@pages_bp.route('/input')
def input_mode():
    return _serve('input')


@pages_bp.route('/input/<path:img>')
def input_image(img):
  img, dpi, scale = _parse_dpi_scale(img)
  return _serve('input', img, initial_dpi=dpi, initial_scale=scale)


@pages_bp.route('/mark/<path:img>')
def mark_image(img):
  img, dpi, scale = _parse_dpi_scale(img)
  return _serve('label', img, initial_dpi=dpi, initial_scale=scale)
