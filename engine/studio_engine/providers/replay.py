"""Replay provider: answers from a recorded run (a folder with params.json, g.png and optionally receipt.json / brief.json),
so the whole pipeline can run offline, in tests and in CI, and reproduce a real ChatGPT run exactly."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .base import ImageEditor, NotConfigured, Usage, VisionModel


def _dir(folder: str) -> Path:
    d = Path(folder or '')
    if not folder or not d.is_dir():
        raise NotConfigured(f'replay: folder not found: {folder!r}')
    return d


class ReplayVision(VisionModel):
    def __init__(self, folder: str):
        self.dir, self.usage = _dir(folder), Usage()

    def brief(self, image_path, user_text):
        self.usage.calls += 1
        if (self.dir / 'brief.json').exists():
            return json.loads((self.dir / 'brief.json').read_text(encoding='utf-8'))
        params = json.loads((self.dir / 'params.json').read_text(encoding='utf-8'))
        genre = 'other'
        if (self.dir / 'receipt.json').exists():
            genre = json.loads((self.dir / 'receipt.json').read_text(encoding='utf-8')).get('genre') or 'other'
        return {'story': 'replay', 'subject': 'replay', 'genre': 'museum' if genre == 'museum' else 'other',
                'portrait': False, 'g_intent': 'replay', 'params': params, 'raw_params': True}


class ReplayEditor(ImageEditor):
    def __init__(self, folder: str):
        self.dir, self.usage = _dir(folder), Usage()

    def edit(self, image_path, prompt, out_path):
        self.usage.calls += 1
        gs = sorted(self.dir.glob('g*.png'))
        src = self.dir / 'g.png' if (self.dir / 'g.png').exists() else gs[min(self.usage.calls - 1, len(gs) - 1)]
        shutil.copy(src, out_path)
        return out_path
