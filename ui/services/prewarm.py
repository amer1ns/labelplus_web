import os
import threading

from core.comic import get_comic_dir

from ui.config import PREWARM_COUNT
from ui.services.image_variants import Image, generate_variant_if_needed


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
