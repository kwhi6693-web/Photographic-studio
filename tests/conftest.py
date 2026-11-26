import json, subprocess, sys
from pathlib import Path
import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / 'photographic-studio'
TOOLS = PKG / 'optional'
# v1.6.2: the v1.4 default route (finish.py, settle.py, harmonize.py ... and the pre-slim pipeline.py / g_first.py)
# lives in the repository's legacy/v1.4/optional, a complete pre-slim snapshot; its tests run it from there.
LEGACY = ROOT / 'legacy' / 'v1.4' / 'optional'
NEW_ROUTE = ('--g-direct', '--quick-n', '--help')
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(TOOLS))
sys.path.append(str(LEGACY))      # legacy-only modules (settle, harmonize ...) import from here, after the package
import synth  # noqa: E402
from ps_common import srgb_to_lab  # noqa: E402


def tool_dir(name, args=()):
    """Packaged tools run from the package; archived ones, and pipeline.py / g_first.py on the old route, from legacy."""
    if name in ('pipeline.py', 'g_first.py'):
        return TOOLS if any(str(a) in NEW_ROUTE for a in args) else LEGACY
    return TOOLS if (TOOLS / name).exists() else LEGACY


def load_legacy(name):
    """Import a module of the legacy/v1.4 snapshot as its own copy (its imports resolve inside the snapshot); the
    package's modules stay what every other test imports."""
    import importlib
    ours = lambda: [k for k in list(sys.modules) if (LEGACY / f'{k}.py').exists()]
    saved = {k: sys.modules.pop(k) for k in ours()}
    sys.path.insert(0, str(LEGACY))
    try:
        module = importlib.import_module(name)
    finally:
        sys.path.remove(str(LEGACY))
        for k in ours():
            sys.modules.pop(k)
        sys.modules.update(saved)
    return module


def run_tool(name, *args):
    """Run one tool exactly as an agent would: a separate process, unmodified."""
    return subprocess.run([sys.executable, '-B', str(tool_dir(name, args) / name), *map(str, args)],
                          capture_output=True, text=True)


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
