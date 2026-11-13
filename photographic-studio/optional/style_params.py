#!/usr/bin/env python3
"""Photographic Studio v1.2.0 - "风格：xx": grade parameters and a G phrase for a named style from assets/styles.json.
Usage: python3 -I style_params.py STYLE OUT_PARAMS_JSON [--base=PARAMS_JSON]   (STYLE: key or Chinese name)
       python3 -I style_params.py --list
With --base, the director's own parameters are kept and the style's are added on top (a style value replaces the same
key). Prints JSON with the style's G phrase, what it fits and what to avoid. The physics and intensity checks still decide.
"""
import json, sys
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / 'assets' / 'styles.json'


def load():
    return json.loads(LIB.read_text(encoding='utf-8'))['styles']


def find(styles, name):
    for k, v in styles.items():
        if name in (k, v['name']): return k, v
    raise SystemExit(f'unknown style: {name}; known: ' + ', '.join(f"{k} ({v['name']})" for k, v in styles.items()))


def merge(base, extra):
    out = json.loads(json.dumps(base))
    for k, v in extra.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def main(argv):
    styles = load()
    if '--list' in argv:
        print(json.dumps({k: {'name': v['name'], 'fits': v['fits'], 'avoid': v['avoid']} for k, v in styles.items()}, ensure_ascii=False, indent=1)); return
    args = [x for x in argv if not x.startswith('--')]
    opt = {x.split('=')[0]: x.split('=', 1)[1] for x in argv if x.startswith('--') and '=' in x}
    if len(args) != 2:
        print(__doc__); sys.exit(2)
    key, st = find(styles, args[0])
    base = json.loads(Path(opt['--base']).read_text(encoding='utf-8')) if '--base' in opt else {}
    params = merge(base, st['params'])
    Path(args[1]).write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'tool': 'style_params.py v1.2.0', 'style': key, 'name': st['name'], 'g_phrase': st['g_phrase'],
                      'fits': st['fits'], 'avoid': st['avoid'], 'params': params}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
