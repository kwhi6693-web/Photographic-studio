"""The SKILL.md flow (steps 2-8) as code. Order and retry rules follow SKILL.md v1.0.7:

  measure -> read + brief (vision) -> G (image) -> scene check -> finish.py -> [G rejected: one corrected G] ->
  settle.py -> n_trim.py -> final checks -> receipt

Not yet in the engine (the skill does them by eye): reframe (step 7), the optional one-round manual refine of step 6.
Works at the skill's working size (long side 1536). Full-resolution output is a later step (see engine/README.md).
"""
import json, shutil, subprocess, sys, time
from pathlib import Path
from .config import Config
from . import prompts
from .providers import vision_provider, image_provider, ProviderError

WORK_SIDE = 1536


class Run:
    def __init__(self, cfg, out):
        self.cfg, self.out = cfg, Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.rec = {'engine': 'studio 0.1.0', 'steps': [], 'calls': {'vision': 0, 'image': 0}}
        self.t0 = time.time()

    def step(self, name, **info):
        info['name'] = name; info['t'] = round(time.time() - self.t0, 1)
        self.rec['steps'].append(info); return info

    def tool(self, script, *args, parse=True):
        p = subprocess.run([sys.executable, '-B', str(self.cfg.tools / script), *map(str, args)], capture_output=True, text=True)
        if not parse: return p
        try: return json.loads(p.stdout)
        except Exception: return {'verdict': 'TOOL_ERROR', 'stderr': p.stderr[-500:], 'stdout': p.stdout[-300:]}


def _work_copy(src, dst):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(src)).convert('RGB')
    s = WORK_SIDE / max(im.size)
    if s < 1: im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    im.save(dst, 'JPEG', quality=95)
    return im.size


def run(photo, out_dir, cfg: Config = None, **override):
    cfg = cfg or Config.from_env(**override)
    if 'replay' in (cfg.vision, cfg.image) and not cfg.replay_dir: cfg.replay_dir = str(Path(photo).resolve().parent)
    R = Run(cfg, out_dir); o = R.out
    vision, image = vision_provider(cfg), image_provider(cfg)

    # 1. working copy (the replay provider works on the recorded original as it is)
    if cfg.vision == 'replay' and cfg.image == 'replay':
        src = o / ('original' + Path(photo).suffix.lower()); shutil.copy(photo, src)
    else:
        src = o / 'original.jpg'; _work_copy(photo, src)
    R.step('prepare', size=list(__import__('PIL.Image', fromlist=['Image']).open(src).size))

    # 2-4. measure, read, brief
    measure = R.tool('measure.py', src); (o / 'measure.json').write_text(json.dumps(measure, ensure_ascii=False, indent=1))
    try:
        brief = vision.read(src, prompts.reading_prompt(measure)); R.rec['calls']['vision'] += 1
    except ProviderError as e:
        return _fail(R, f'vision: {e}')
    brief['params'] = prompts.clean_params(brief.get('params') or {})
    if brief.get('genre') not in prompts.GENRES: brief['genre'] = 'day'
    (o / 'brief.json').write_text(json.dumps(brief, ensure_ascii=False, indent=1))
    (o / 'params.json').write_text(json.dumps(brief['params']))
    R.step('brief', genre=brief['genre'], params=brief['params'])
    if brief.get('is_portrait'):
        R.rec['result'] = 'REFUSED: portrait'; return _done(R)
    gopt = ['--genre=museum'] if brief['genre'] == 'museum' else []

    # 5. G, scene check, finish; a rejected G gets one corrected retry
    def draw(prompt, k):
        if image is None or R.rec['calls']['image'] >= cfg.g_max: return None
        try:
            data = image.edit(src, prompt); R.rec['calls']['image'] += 1
        except ProviderError as e:
            R.step('g_error', error=str(e)[:300]); return None
        g = o / f'g{k}.png'; g.write_bytes(data)
        (o / f'g{k}_prompt.txt').write_text(prompt, encoding='utf-8')
        chk = R.tool('check_g_output.py', src, g)
        R.step('g', k=k, scene_ok=chk.get('scene_correspondence_ok'), verdict=str(chk.get('verdict'))[:80])
        return g if chk.get('scene_correspondence_ok') else None

    def finish(g, k):
        out, rj = o / f'finish{k}.png', o / f'finish{k}.json'
        R.tool('finish.py', src, g or src, o / 'params.json', out, rj, *gopt, parse=False)
        r = json.loads(rj.read_text()) if rj.exists() else {}
        R.step('finish', k=k, delivered=r.get('delivered'), verdict=str(r.get('verdict'))[:100])
        return out, r

    prompt = prompts.g_prompt(brief.get('g_intent', ''))
    g = draw(prompt, 1)
    if g is None and R.rec['calls']['image'] == 1:          # scene mismatch: one more try, same intent
        g = draw(prompts.g_prompt(brief.get('g_intent', ''), 'Keep exactly the same framing, objects and layout as the source.'), 2)
    fin, frec = finish(g, 1)
    route = str(frec.get('delivered') or '')
    if g is not None and route.startswith('n_direct') and R.rec['calls']['image'] < cfg.g_max:
        problems = [p for a in frec.get('attempts', []) if not a['name'].startswith('n_direct')
                    for p in a.get('problems', []) + a.get('strength_problems', [])]
        g2 = draw(prompts.g_prompt(brief.get('g_intent', ''), prompts.correction_for(problems)), 2)
        if g2 is not None:
            fin2, frec2 = finish(g2, 2)
            if not str(frec2.get('delivered') or '').startswith('n_direct'):
                fin, frec, route = fin2, frec2, str(frec2.get('delivered'))
    R.rec['route'] = route

    # 6. settle (one call), 8. n_trim
    settled = o / 'settled.png'
    sargs = [src, fin, settled, o / 'settle.json', *gopt] + (['--n-direct'] if route.startswith('n_direct') else [])
    R.tool('settle.py', *sargs, parse=False)
    if not settled.exists(): shutil.copy(fin, settled)
    trimmed = o / 'trimmed.png'
    R.tool('n_trim.py', settled, trimmed, o / 'trim.json', parse=False)
    final = o / 'final.png'; shutil.copy(trimmed if trimmed.exists() else settled, final)

    it = R.tool('intensity_check.py', src, final, *gopt); ph = R.tool('physics_check.py', src, final)
    R.rec['final'] = {'intensity': it.get('verdict'), 'physics': ph.get('verdict')}
    R.rec['result'] = 'DELIVERED'
    return _done(R)


def _fail(R, why):
    R.rec['result'] = 'FAILED: ' + why; return _done(R)


def _done(R):
    c = R.cfg; R.rec['seconds'] = round(time.time() - R.t0, 1)
    R.rec['cost_usd_estimate'] = round(R.rec['calls']['image'] * c.price_image + R.rec['calls']['vision'] * c.price_vision, 4)
    (R.out / 'receipt.json').write_text(json.dumps(R.rec, ensure_ascii=False, indent=1))
    return R.rec
