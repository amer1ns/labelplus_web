import os


def _int_env(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


# number of images to prewarm on startup (first N)
PREWARM_COUNT = _int_env('PREWARM_COUNT', 8)

# neighbor prewarm radius when flipping pages
NEIGHBOR_PREWARM_RADIUS = _int_env('NEIGHBOR_PREWARM_RADIUS', 2)
