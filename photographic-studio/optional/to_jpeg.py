#!/usr/bin/env python3
"""Photographic Studio v1.6.0 - delivery copy: any image -> sRGB JPEG (quality 95, same pixel size).
Usage: python3 to_jpeg.py INPUT OUTPUT_JPG
Why: on the ChatGPT iPhone app an image shown inside the chat by code cannot be saved to Photos, while a .jpg
offered as a link opens a preview whose Share sheet has "Save Image" (user test 2026-11-26: JPEG link and PNG link
both saved; inline JPEG did not). JPEG keeps the file small; a PNG of a phone photo is several times larger and no
sharper. Pure Pillow.
"""
import json, sys
from pathlib import Path
from PIL import Image


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    img = Image.open(src)
    img = img.convert('RGB')          # drops alpha and any non-sRGB mode; the pipeline already works in sRGB
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, 'JPEG', quality=95, subsampling=0, optimize=True)
    print(json.dumps({'tool': 'to_jpeg.py v1.6.0', 'output': dst, 'size': list(img.size),
                      'bytes': Path(dst).stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
