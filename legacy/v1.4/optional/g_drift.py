#!/usr/bin/env python3
"""Photographic Studio v1.4.1 - read-only G appearance diagnostics on the original pixel grid.

Use --save-aligned to export the reference and valid area for a later crop.
With --aligned, pass --source if original-relative metrics are needed. The
source must already have the same framing as the aligned reference and images.
"""
import argparse
import json

import numpy as np
from PIL import Image

from look_transfer import cv2, register
from ps_common import blur, load_rgb, midfreq, save_png, srgb_to_lab, structure_mask


def align(source, g):
    matrix, inliers = register(source, g)
    if matrix is None:
        raise ValueError(f'G registration failed ({inliers} inliers)')
    h, w = source.shape[:2]
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    aligned = cv2.warpPerspective(g, matrix, (w, h), flags=flags,
                                  borderMode=cv2.BORDER_REPLICATE)
    coverage = cv2.warpPerspective(np.ones(g.shape[:2], np.float32), matrix, (w, h), flags=flags)
    interior = np.pad(coverage >= 0.999, 3, constant_values=False).astype(np.uint8)
    valid = cv2.erode(interior, np.ones((7, 7), np.uint8))[3:-3, 3:-3] != 0
    return aligned, valid, inliers


def ratio(value, reference):
    return value / reference if reference is not None and abs(reference) > 1e-6 else None


class Measurements:
    def __init__(self, g, valid, source=None, inliers=None):
        if valid.shape != g.shape[:2] or not valid.any():
            raise ValueError('G requires a matching, nonempty valid mask')
        self.shape = g.shape
        self.valid = valid
        self.inliers = inliers
        self.radius = max(4, round(0.0075 * min(valid.shape)))
        source_lab = None if source is None else self.lab(source)
        self.structure = None if source_lab is None else valid & (structure_mask(source_lab[..., 0]) > 0.5)
        if self.structure is not None and not self.structure.any():
            self.structure = None
        self.g = self.stats(srgb_to_lab(g))
        self.source = None if source_lab is None else self.stats(source_lab)
        self.source_de = None if self.source is None else self.distance(self.source['low'])

    def lab(self, rgb):
        if rgb.shape != self.shape:
            raise ValueError(f'image size {rgb.shape[:2]} does not match G {self.shape[:2]}')
        return srgb_to_lab(rgb)

    def stats(self, lab):
        light = lab[..., 0]
        samples = lab[self.valid]
        contrast = None
        if self.structure is not None:
            contrast = float(np.abs(midfreq(light)[self.structure]).mean())
        return {
            'low': np.stack([blur(lab[..., i], self.radius)[self.valid] for i in range(3)], axis=-1),
            'mean': float(samples[:, 0].mean()),
            'percentiles': np.percentile(samples[:, 0], [10, 50, 90]),
            'chroma': float(np.hypot(samples[:, 1], samples[:, 2]).mean()),
            'midfreq': contrast,
        }

    def distance(self, low):
        return float(np.linalg.norm(low - self.g['low'], axis=-1).mean())

    def measure(self, rgb):
        image = self.stats(self.lab(rgb))
        de = self.distance(image['low'])
        fraction = ratio(de, self.source_de)
        chroma = None
        if self.source is not None:
            base = self.source['chroma']
            change = self.g['chroma'] - base
            if abs(change) >= 1.0:
                chroma = (image['chroma'] - base) / change
        lam = image['percentiles'] - self.g['percentiles']
        return {
            'lowfreq_dE_to_G': de,
            'lowfreq_dE_source_to_G': self.source_de,
            'look_captured': None if fraction is None else 1 - fraction,
            'L_p10_minus_G': float(lam[0]),
            'L_p50_minus_G': float(lam[1]),
            'L_p90_minus_G': float(lam[2]),
            'L_mean_minus_G': image['mean'] - self.g['mean'],
            'chroma_retention': chroma,
            'chroma_ratio_to_G': ratio(image['chroma'], self.g['chroma']),
            'midfreq_ratio_to_G': None if image['midfreq'] is None else ratio(image['midfreq'], self.g['midfreq']),
            'midfreq_ratio_to_source': None if image['midfreq'] is None else ratio(image['midfreq'], self.source['midfreq']),
            'registration_inliers': self.inliers,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', help='source image, or aligned G with --aligned')
    parser.add_argument('target', help='G image, or valid mask with --aligned')
    parser.add_argument('images', nargs='+')
    parser.add_argument('--names', required=True, help='comma-separated stage names')
    parser.add_argument('--save-aligned', help='output G and mask PNG filenames, separated by a comma')
    parser.add_argument('--aligned', action='store_true')
    parser.add_argument('--source', help='original framed like G, for --aligned')
    parser.add_argument('--inliers', type=int, help='registration inliers to carry over with --aligned')
    args = parser.parse_args()
    names = args.names.split(',')
    if len(names) != len(args.images) or len(set(names)) != len(names) or not all(names):
        parser.error('--names must supply one unique nonempty name per image')
    if (args.aligned and args.save_aligned) or (not args.aligned and (args.source or args.inliers is not None)):
        parser.error('use --source and --inliers with --aligned, or --save-aligned with registration')
    outputs = args.save_aligned.split(',') if args.save_aligned else []
    if outputs and (len(outputs) != 2 or not all(outputs)):
        parser.error('--save-aligned needs two output filenames')
    try:
        if args.aligned:
            g = load_rgb(args.reference)
            with Image.open(args.target) as mask:
                valid = np.asarray(mask.convert('L')) == 255
            source = load_rgb(args.source) if args.source else None
            inliers = args.inliers
        else:
            source = load_rgb(args.reference)
            g, valid, inliers = align(source, load_rgb(args.target))
        meter = Measurements(g, valid, source, inliers)
        results = {name: meter.measure(load_rgb(path)) for name, path in zip(names, args.images)}
        if outputs:
            save_png(g, outputs[0])
            Image.fromarray(valid.astype(np.uint8) * 255).save(outputs[1], format='PNG')
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(results, indent=1, allow_nan=False))


if __name__ == '__main__':
    main()
