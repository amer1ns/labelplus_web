import os

from core.comic import get_comic_dir

# optional dependency: Pillow. Install with `pip install Pillow`.
try:
  from PIL import Image
except Exception:
  Image = None


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
