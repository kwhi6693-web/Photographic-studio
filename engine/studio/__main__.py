"""python -m studio run PHOTO OUT_DIR          one photo
python -m studio eval PHOTO_DIR OUT_DIR [--runs=2]   the fixed evaluation set
python -m studio serve [--port=8000]         the HTTP API for the app
python -m studio check                       which providers and keys are configured (keys are never printed)
"""
import json, sys
from .config import Config


def main(argv):
    if not argv or argv[0] in ('-h', '--help'): print(__doc__); return 0
    opt = dict(a[2:].split('=', 1) for a in argv if a.startswith('--') and '=' in a)
    args = [a for a in argv[1:] if not a.startswith('--')]
    cmd = argv[0]
    if cmd == 'check':
        c = Config.from_env()
        print(json.dumps({'vision': c.vision, 'image': c.image, 'openai_key_set': bool(c.openai_key),
                          'gemini_key_set': bool(c.gemini_key), 'openai_models': [c.openai_vision_model, c.openai_image_model],
                          'gemini_models': [c.gemini_vision_model, c.gemini_image_model], 'tools': str(c.tools),
                          'tools_found': (c.tools / 'finish.py').exists()}, indent=1)); return 0
    if cmd == 'run':
        from .pipeline import run
        r = run(args[0], args[1]); print(json.dumps(r, ensure_ascii=False, indent=1)); return 0 if r.get('result') == 'DELIVERED' else 1
    if cmd == 'eval':
        from .evaluate import evaluate
        s = evaluate(args[0], args[1], int(opt.get('runs', 2))); print(json.dumps({k: v for k, v in s.items() if k != 'rows'}, ensure_ascii=False, indent=1)); return 0
    if cmd == 'serve':
        import uvicorn
        uvicorn.run('studio.server:app', host=opt.get('host', '127.0.0.1'), port=int(opt.get('port', 8000))); return 0
    print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
