"""Command line.

    python -m studio_engine.cli run PHOTO OUT_DIR [--config=...]     one photo
    python -m studio_engine.cli selftest [--config=...]              is everything configured? (no paid call unless --live)
    python -m studio_engine.cli selftest --live                      one tiny real call to each configured model
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

from .config import load
from .pipeline import Studio
from .providers import NotConfigured, ProviderError


def selftest(cfg_path=None, live=False) -> dict:
    cfg = load(cfg_path)
    rep = {'tools_dir': str(cfg.tools_dir), 'tools_found': (cfg.tools_dir / 'finish.py').exists()}
    for role, p in (('vision', cfg.vision), ('editor', cfg.editor)):
        rep[role] = {'provider': p.name, 'model': p.model or '(empty)', 'api_key': 'set' if p.api_key else '(empty)'}
        if p.name != 'replay' and (not p.api_key or not p.model):
            rep[role]['status'] = 'NOT CONFIGURED: fill engine/config.toml or set the API key environment variable'
        else:
            rep[role]['status'] = 'configured'
    if live:
        st = Studio(cfg)
        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / 'grey.jpg'; Image.new('RGB', (256, 256), (120, 130, 140)).save(img)
            for role, fn in (('vision', lambda: st.vision.brief(str(img), 'selftest: a plain grey square')),
                             ('editor', lambda: st.editor.edit(str(img), 'Return the same image.', str(Path(td) / 'g.png')))):
                try:
                    fn(); rep[role]['live'] = 'OK'
                except (NotConfigured, ProviderError) as e:
                    rep[role]['live'] = f'FAILED: {e}'
    return rep


def main(argv=None):
    argv = argv or sys.argv[1:]
    a = [x for x in argv if not x.startswith('--')]
    o = dict(x[2:].split('=', 1) for x in argv if x.startswith('--') and '=' in x)
    if not a:
        sys.exit(__doc__)
    if a[0] == 'selftest':
        print(json.dumps(selftest(o.get('config'), '--live' in argv), ensure_ascii=False, indent=1)); return
    if a[0] == 'run' and len(a) >= 3:
        r = Studio(load(o.get('config'))).run(a[1], a[2])
        print(json.dumps({'status': r.status, 'final': r.final, 'route': r.route, 'reason': r.reason,
                          'seconds': r.receipt.get('seconds_total'), 'cost_usd': r.receipt.get('usage', {}).get('cost_usd_estimate')},
                         ensure_ascii=False, indent=1))
        sys.exit(0 if r.status != 'failed' else 1)
    sys.exit(__doc__)


if __name__ == '__main__':
    main()
