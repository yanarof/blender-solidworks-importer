"""Most common saturated colours in PNG files, using Blender's image loader.

usage: blender --background --factory-startup --python preview_colors.py -- <png> [<png> ...]
"""

import sys
from collections import Counter

import bpy
import numpy as np

for path in sys.argv[sys.argv.index("--") + 1 :]:
    image = bpy.data.images.load(path)
    pixels = np.empty(image.size[0] * image.size[1] * 4, np.float32)
    image.pixels.foreach_get(pixels)
    rgb = (np.clip(pixels.reshape(-1, 4)[:, :3], 0, 1) ** (1 / 2.2) * 255).astype(int)
    spread = rgb.max(axis=1) - rgb.min(axis=1)
    saturated = rgb[spread > 40]
    counts = Counter(tuple(int(v) for v in c // 16 * 16) for c in saturated)
    red = int(((rgb[:, 0] > rgb[:, 1] + 50) & (rgb[:, 0] > rgb[:, 2] + 50)).sum())
    blue = int(((rgb[:, 2] > rgb[:, 0] + 50) & (rgb[:, 2] > rgb[:, 1] + 50)).sum())
    print(f"COLORS {path.rsplit(chr(92), 1)[-1]}: total={len(rgb)} reddish={red} bluish={blue} top={counts.most_common(8)}")
