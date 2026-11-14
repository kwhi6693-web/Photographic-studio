"""Offline provider: replays a recorded run (params.json and g.png from a ChatGPT batch folder). No key, no network.
Used by the tests, and to check that the engine reproduces a recorded ChatGPT result exactly."""
import json
from pathlib import Path
from .base import ProviderError


class ReplayProvider:
    def __init__(self, cfg):
        self.dir = Path(cfg.replay_dir) if cfg.replay_dir else None

    def _d(self, photo):
        d = self.dir or Path(photo).parent
        if not (d / 'params.json').exists(): raise ProviderError(f'replay: no params.json in {d}')
        return d

    def read(self, photo, prompt):
        d = self._d(photo)
        rec = json.loads((d / 'receipt.json').read_text()) if (d / 'receipt.json').exists() else {}
        genre = rec.get('genre') or 'day'
        return {'is_portrait': False, 'genre': genre if genre in ('day', 'night', 'lowcolour', 'museum') else 'day',
                'story_style': '(replay)', 'subject': '', 'tone': '', 'colour': '', 'keep': '',
                'g_intent': '(replay)', 'params': json.loads((d / 'params.json').read_text())}

    def edit(self, photo, prompt):
        g = self._d(photo) / 'g.png'
        if not g.exists(): raise ProviderError('replay: no g.png')
        return g.read_bytes()
