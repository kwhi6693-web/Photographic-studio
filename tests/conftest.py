import json, subprocess, sys
from pathlib import Path
import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / 'photographic-studio'
TOOLS = PKG / 'optional'
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(TOOLS))
import synth  # noqa: E402
from ps_common import srgb_to_lab  # noqa: E402


def run_tool(name, *args):
    """Run one packaged tool exactly as an agent would: a separate process, unmodified."""
    return subprocess.run([sys.executable, '-B', str(TOOLS / name), *map(str, args)], capture_output=True, text=True)


def load(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(np.float32) / 255.0


def L(a):
    return srgb_to_lab(a)[..., 0]


def detail(a):
    g = a.mean(-1)
    return g - synth._blur(g, 2)


@pytest.fixture
def scene(tmp_path):
    def make(name):
        return synth.save(synth.SCENES[name](), tmp_path / f'{name}.png')
    return make


@pytest.fixture
def finish(tmp_path):
    def go(src, g, params=None, genre=None, tag='f'):
        pj = tmp_path / f'{tag}.json'
        pj.write_text(json.dumps(params or {}))
        out, rec = tmp_path / f'{tag}.png', tmp_path / f'{tag}_receipt.json'
        p = run_tool('finish.py', src, g, pj, out, rec, *([f'--genre={genre}'] if genre else []))
        assert p.returncode == 0, p.stderr[-800:]
        return out, json.loads(rec.read_text())
    return go
