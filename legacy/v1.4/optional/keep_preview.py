#!/usr/bin/env python3
"""Photographic Studio v1.4.6 - keep box preview. Usage: python3 keep_preview.py ORIGINAL PARAMS_JSON PREVIEW_PNG
Draws the brief's "keep" boxes on the original over a 10 x 10 grid (lines every 0.1, labelled on the edges), so the
agent can look once and see whether every box really covers the sign, person or exhibit it names, before G is called.
2026-11-25/26 batches: keep boxes listed the right things but several sat in empty sky or on the ceiling, and the
tools reported KEPT anyway - the coordinates are the agent's estimate and no tool can tell what a box was meant to hold.
Pillow only (no numpy, no OpenCV). Boxes are numbered; the JSON report maps numbers to what each box is for.
"""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from keep_regions import regions_of   # noqa: E402  (same box parsing as the restore step)

LONG_SIDE = 1600
COLOURS = [(255, 40, 40), (255, 200, 0), (0, 220, 255), (255, 0, 255), (60, 255, 60), (255, 140, 0)]


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    source, params_path, out = sys.argv[1:]
    params = json.loads(Path(params_path).read_text(encoding='utf-8') or '{}')
    regions = regions_of(params)
    image = ImageOps.exif_transpose(Image.open(source)).convert('RGB')
    image.thumbnail((LONG_SIDE, LONG_SIDE))
    width, height = image.size
    draw = ImageDraw.Draw(image)
    try:   # Pillow >= 10.1 scales the built-in font; older Pillow keeps the small bitmap font
        small = ImageFont.load_default(size=max(14, round(min(width, height) / 60)))
        large = ImageFont.load_default(size=max(24, round(min(width, height) / 30)))
    except TypeError:
        small = large = ImageFont.load_default()
    for step in range(1, 10):
        x, y = round(width * step / 10), round(height * step / 10)
        draw.line([(x, 0), (x, height)], fill=(255, 255, 255), width=1)
        draw.line([(0, y), (width, y)], fill=(255, 255, 255), width=1)
        label = f'0.{step}'
        for position in ((x + 3, 3), (x + 3, height - small.size - 6 if hasattr(small, 'size') else height - 14)):
            draw.text(position, label, fill=(255, 255, 255), font=small, stroke_width=2, stroke_fill=(0, 0, 0))
        for position in ((3, y + 3), (width - 3 * getattr(small, 'size', 9), y + 3)):
            draw.text(position, label, fill=(255, 255, 255), font=small, stroke_width=2, stroke_fill=(0, 0, 0))
    thickness = max(3, round(min(width, height) / 250))
    report = []
    for number, region in enumerate(regions, 1):
        x0, y0, x1, y1 = region['box']
        colour = COLOURS[(number - 1) % len(COLOURS)]
        draw.rectangle([x0 * width, y0 * height, x1 * width, y1 * height], outline=colour, width=thickness)
        draw.text((x0 * width + thickness + 2, y0 * height + thickness + 2), str(number), fill=colour, font=large,
                  stroke_width=3, stroke_fill=(0, 0, 0))
        report.append({'number': number, 'what': region['what'], 'box': region['box'], 'mode': region['mode']})
    image.save(out)
    print(json.dumps({'tool': 'keep_preview.py v1.4.6', 'preview': str(out), 'boxes': report,
                      'verdict': 'LOOK: check every numbered box covers what it names; fix the brief and redraw'
                                 if report else 'NO_REGIONS: nothing to protect - say why in one line'},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
