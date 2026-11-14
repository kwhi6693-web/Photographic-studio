"""full_res.py: an edit made at a small working size, carried back to full size, must match the edit made at full size
far better than a plain upscale, and keep the original's fine detail."""
import json

import cv2
import numpy as np
from PIL import Image

from conftest import ROOT, run_tool

REAL = ROOT / 'tests' / 'fixtures' / 'real'


def test_full_res_reproduces_a_full_size_edit(tmp_path):
    src = REAL / '03_canal.jpg'
    full = Image.open(src).convert('RGB')
    pj = tmp_path / 'p.json'; pj.write_text(json.dumps({'exposure_ev': 0.25, 'vibrance': 0.3, 'contrast': 0.1}))
    truth = tmp_path / 'truth.png'
    assert run_tool('grade.py', src, truth, pj).returncode == 0          # the edit at full size = ground truth
    half = (full.width // 2, full.height // 2)
    wo, wf = tmp_path / 'wo.png', tmp_path / 'wf.png'
    full.resize(half, Image.LANCZOS).save(wo); Image.open(truth).resize(half, Image.LANCZOS).save(wf)
    out = tmp_path / 'out.png'
    p = run_tool('full_res.py', src, wo, wf, out)
    assert p.returncode == 0 and json.loads(p.stdout)['verdict'] == 'PASS'
    A = np.asarray(Image.open(out).convert('RGB'), np.float32); T = np.asarray(Image.open(truth).convert('RGB'), np.float32)
    U = np.asarray(Image.open(wf).resize(full.size, Image.BICUBIC).convert('RGB'), np.float32)
    assert np.abs(A - T).mean() < 0.5 * np.abs(U - T).mean()
    det = lambda x: np.abs(x.mean(2) - cv2.GaussianBlur(x.mean(2), (0, 0), 1.2)).mean()
    assert det(A) > 0.85 * det(T)
