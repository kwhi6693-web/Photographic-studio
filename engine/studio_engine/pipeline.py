"""The Photographic Studio pipeline as code: what SKILL.md asks the agent to do, step by step, without the agent.

    studio.run(photo, out_dir) -> Result     one photo in, one finished photo out (or a clear reason why not)

Order (SKILL.md v1.0.9; no crop step yet): measure -> brief (vision model) -> portrait? stop -> G (image model) -> scene check (retry once)
-> finish.py (route ladder) -> G rejected? re-call G once with the problems named -> settle.py -> n_trim.py -> final.
Every step is timed and written to receipt.json; model usage and estimated cost too.
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from . import prompts
from .config import EngineConfig
from .providers import ImageEditor, NotConfigured, ProviderError, VisionModel, make_editor, make_vision
from .tools import ToolError, Tools

VERSION = '2.2.0'


class _SkipG(Exception):
    """v1.0.9: the brief says the light is already good, so the image model is not called."""


@dataclass
class Result:
    status: str                      # 'done' | 'unsupported' | 'failed'
    final: str | None = None
    route: str = ''
    reason: str = ''
    receipt: dict = field(default_factory=dict)


class Studio:
    def __init__(self, cfg: EngineConfig, vision: VisionModel | None = None, editor: ImageEditor | None = None):
        self.cfg = cfg
        self.tools = Tools(cfg.tools_dir, timeout_s=max(900, cfg.timeout_s))
        self.vision = vision or make_vision(cfg.vision, cfg)
        self.editor = editor or make_editor(cfg.editor, cfg)

    # -- helpers ---------------------------------------------------------------------------------
    def _working_copy(self, photo: Path, out: Path) -> Path:
        im = ImageOps.exif_transpose(Image.open(photo)).convert('RGB')
        self._downscaled = max(im.size) > self.cfg.work_size
        if max(im.size) <= self.cfg.work_size and photo.suffix.lower() in ('.jpg', '.jpeg', '.png'):
            dst = out / ('original' + photo.suffix.lower()); shutil.copy(photo, dst); return dst
        s = self.cfg.work_size / max(im.size)
        if s < 1:
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        dst = out / 'original.jpg'; im.save(dst, 'JPEG', quality=95)
        return dst

    def _g(self, src: Path, prompt: str, out: Path, rec: dict) -> Path | None:
        """One G call plus the scene check. Returns the G draft, or None when it does not match the scene."""
        n = rec['g_calls'] = rec.get('g_calls', 0) + 1
        g = out / f'g{n}.png'
        t = time.time()
        self.editor.edit(str(src), prompt, str(g))
        chk = self.tools.check_g(src, g)
        rec['steps'].append({'step': f'g{n}', 'seconds': round(time.time() - t, 1), 'prompt': prompt,
                             'check': chk.get('verdict'), 'scene_ok': chk.get('scene_correspondence_ok')})
        return g if chk.get('scene_correspondence_ok', True) else None

    # -- the pipeline ----------------------------------------------------------------------------
    def run(self, photo: str | Path, out_dir: str | Path) -> Result:
        photo, out = Path(photo), Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        rec: dict = {'engine': VERSION, 'photo': photo.name, 'steps': [], 'g_calls': 0}

        def done(res: Result) -> Result:
            rec['seconds_total'] = round(time.time() - t0, 1)
            rec['usage'] = {'vision': vars(self.vision.usage), 'editor': vars(self.editor.usage),
                            'cost_usd_estimate': round(self.vision.usage.cost_usd + self.editor.usage.cost_usd, 4)}
            rec.update(status=res.status, route=res.route, reason=res.reason)
            (out / 'receipt.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
            res.receipt = rec
            return res

        try:
            src = self._working_copy(photo, out)
            t = time.time(); meas = self.tools.measure(src)
            rec['steps'].append({'step': 'measure', 'seconds': round(time.time() - t, 1)})

            t = time.time(); raw = self.vision.brief(str(src), prompts.brief_user_text(meas))
            brief = raw if raw.get('raw_params') else prompts.clamp_brief(raw)
            (out / 'brief.json').write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding='utf-8')
            rec['steps'].append({'step': 'brief', 'seconds': round(time.time() - t, 1), 'genre': brief.get('genre')})
            if brief.get('portrait'):
                return done(Result('unsupported', reason='portrait: not retouched by this service'))
            museum = brief.get('genre') == 'museum'
            params = out / 'params.json'
            params.write_text(json.dumps(brief['params']), encoding='utf-8')

            # G: up to two calls; the second only when the first does not match the scene
            g = None
            try:
                if brief.get('light_already_good'):   # v1.0.9: light already right -> N direct with the brief's light params
                    rec['steps'].append({'step': 'g', 'skipped': 'light_already_good'})
                    raise _SkipG()
                g = self._g(src, prompts.g_prompt(brief), out, rec)
                if g is None and rec['g_calls'] < self.cfg.g_max_calls:
                    g = self._g(src, prompts.g_prompt(brief, ['scene']), out, rec)
            except _SkipG:
                pass
            except (ProviderError, ToolError) as e:
                rec['steps'].append({'step': 'g', 'error': str(e)[:400]})   # fall back to N direct
            t = time.time()
            fr = self.tools.finish(src, g or src, params, out / 'finish.png', out / 'finish.json', museum)
            route = fr.get('delivered', '')
            rec['steps'].append({'step': 'finish', 'seconds': round(time.time() - t, 1), 'route': route})

            # v1.0.7: G was rejected by the checks -> name the problems and call G once more
            if g is not None and route.startswith('n_direct') and rec['g_calls'] < self.cfg.g_max_calls:
                probs = sorted({p for a in fr.get('attempts', []) if not a['name'].startswith('n_direct')
                                for p in a.get('problems', []) + (['sky'] if 'sky_L_change' in a.get('strength_problems', []) else [])})
                try:
                    g2 = self._g(src, prompts.g_prompt(brief, probs or ['removed_light']), out, rec)
                    if g2 is not None:
                        t = time.time()
                        fr2 = self.tools.finish(src, g2, params, out / 'finish2.png', out / 'finish2.json', museum)
                        r2 = fr2.get('delivered', '')
                        rec['steps'].append({'step': 'finish2', 'seconds': round(time.time() - t, 1), 'route': r2})
                        if not r2.startswith('n_direct'):
                            shutil.copy(out / 'finish2.png', out / 'finish.png'); route = r2
                except (ProviderError, ToolError) as e:
                    rec['steps'].append({'step': 'g_retry', 'error': str(e)[:400]})

            t = time.time()
            st = self.tools.settle(src, out / 'finish.png', out / 'settled.png', out / 'settle.json', museum,
                                   n_direct=route.startswith('n_direct'))
            rec['steps'].append({'step': 'settle', 'seconds': round(time.time() - t, 1), 'final': st.get('final')})

            t = time.time()
            nt = self.tools.n_trim(out / 'settled.png', out / 'trimmed.png', out / 'trim.json')
            final = out / 'trimmed.png' if str(nt.get('verdict', '')).startswith('PASS') and (out / 'trimmed.png').exists() \
                else out / 'settled.png'
            rec['steps'].append({'step': 'n_trim', 'seconds': round(time.time() - t, 1), 'verdict': str(nt.get('verdict'))[:60]})
            shutil.copy(final, out / 'final.png')
            rec['final_intensity'] = self.tools.intensity(src, out / 'final.png', museum).get('verdict')
            rec['final_physics'] = self.tools.physics(src, out / 'final.png').get('verdict')
            delivered = out / 'final.png'
            if src.name == 'original.jpg' and src.suffix and self._downscaled:   # v2.1.0: back to full resolution
                t = time.time()
                fr_full = self.tools.run('full_res.py', photo, src, out / 'final.png', out / 'final_full.jpg')
                rec['steps'].append({'step': 'full_res', 'seconds': round(time.time() - t, 1), 'verdict': fr_full.get('verdict'),
                                     'size': fr_full.get('full_size')})
                if (out / 'final_full.jpg').exists():
                    delivered = out / 'final_full.jpg'
            return done(Result('done', final=str(delivered), route=route))
        except NotConfigured as e:
            return done(Result('failed', reason=f'not configured: {e}'))
        except (ProviderError, ToolError, OSError) as e:
            return done(Result('failed', reason=str(e)[:600]))
