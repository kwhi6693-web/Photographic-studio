"""Prompts: the director brief the vision model writes, and the G prompt built from it.
Condensed from photographic-studio/references (director_brief.md, g_prompt_template.md, physics.md, intensity.md).
"""
from __future__ import annotations

import json

GENRES = ('day', 'night', 'museum', 'lowcolour', 'interior', 'portrait', 'other')

BRIEF_SYSTEM = """You are the retoucher's eye of Photographic Studio. Read ONE photo (not a portrait) and write its post-processing brief.
Goal: one finished photo that is clearly better yet still the same photo: real light, believable colour, no AI look.
Rules:
- Follow real light physics: keep the light direction and time of day; shadows stay darker and cooler than lit areas; never add a light source or a glow around the subject; dark backgrounds stay dark and clean.
- Parameters come only from THIS photo's problems (v1.0.9). First list the problems the photo really has, each with what you see and a measurement as evidence (e.g. haze over water and walls even when black window frames make the dynamic range wide; blown highlights; washed sky; flat colour), and what is already good and must not change. Every parameter must serve one listed problem, sized to how bad it is; a parameter no problem asks for stays 0. If the light is already good, only refine lightly: do not brighten, do not add colour. There is no default parameter set.
- The subject is lifted by quieting its surroundings, not by inventing light on it.
- moves (v1.2.0, required, 2-3): the improvement moves that make THIS photo better, each on one area (sky, subject, water, foreground...) and visible at normal viewing - what a professional retoucher would do to bring out the point of interest. A photo with no defect still gets moves; "the light is already good" is not a reason to leave it as it is. Each move: what, look (light+ light- colour+ colour- warm+ warm- contrast+), shape (gradient from top/bottom/left/right with end 0..1, or rect/ellipse with box fractions), on_structure true when the area around the subject is smooth sky, haze or a plain wall, and lift (-8..8 L), sat (0.8..1.4), warm (-4..4), clarity (0..0.35); neutral values (0, 1, 0, 0) for what the move does not use.
- keep (the text) lists only key facts that must not change: text, people, structure, signature colours - never whole areas the moves are meant to improve.
- light_already_good: informational only (v1.2.1: the image model is always called); it never means "edit lightly".
- keep_regions (v1.1.0): the areas whose colour must not change (a sign, a label, coloured glass, a painted surface, a wall whose colour is the point) or whose content the image model must not repaint, each as a box in fractions of the frame. mode "colour" keeps the original colour and lets the brightness follow the edit; mode "content" keeps the original's own detail and colour and takes only the large-scale light. Empty if nothing needs it; at most 6.
- If people's faces/bodies are the main subject, set portrait=true (the service does not retouch portraits).
Return ONLY JSON matching the schema. Use the measurements as evidence; trust your eyes when they disagree."""

BRIEF_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['story', 'subject', 'genre', 'portrait', 'diagnoses', 'moves', 'keep', 'keep_regions', 'light_already_good', 'g_intent', 'params'],
    'properties': {
        'story': {'type': 'string', 'description': 'one line: the point of interest (a story is only one kind; also geometry/order, light, colour, texture, mood, space, minimalism) and the style direction'},
        'subject': {'type': 'string', 'description': 'what the subject is and where it is in the frame'},
        'genre': {'type': 'string', 'enum': list(GENRES)},
        'portrait': {'type': 'boolean'},
        'diagnoses': {'type': 'array', 'description': 'v1.0.9: the problems this photo really has (empty if none)',
                      'items': {'type': 'object', 'additionalProperties': False, 'required': ['problem', 'evidence', 'params'],
                                'properties': {'problem': {'type': 'string'}, 'evidence': {'type': 'string'},
                                               'params': {'type': 'array', 'items': {'type': 'string'}, 'description': 'names of the params that fix it'}}}},
        'keep': {'type': 'string', 'description': 'what is already good in this photo and must not change'},
        'keep_regions': {'type': 'array', 'description': 'v1.1.0: regions that must not change (see the rules)',
                         'items': {'type': 'object', 'additionalProperties': False, 'required': ['what', 'box', 'mode'],
                                   'properties': {'what': {'type': 'string'},
                                                  'box': {'type': 'array', 'items': {'type': 'number'}, 'description': '[x0, y0, x1, y1], fractions 0..1'},
                                                  'mode': {'type': 'string', 'enum': ['colour', 'content']}}}},
        'moves': {'type': 'array', 'description': 'v1.2.0: 2-3 visible improvement moves (see the rules)',
                  'items': {'type': 'object', 'additionalProperties': False,
                            'required': ['what', 'look', 'shape', 'box', 'from', 'end', 'on_structure', 'lift', 'sat', 'warm', 'clarity'],
                            'properties': {'what': {'type': 'string'},
                                           'look': {'type': 'string', 'enum': ['light+', 'light-', 'colour+', 'colour-', 'warm+', 'warm-', 'contrast+']},
                                           'shape': {'type': 'string', 'enum': ['gradient', 'rect', 'ellipse']},
                                           'box': {'type': 'array', 'items': {'type': 'number'}, 'description': '[x0, y0, x1, y1] fractions (rect/ellipse)'},
                                           'from': {'type': 'string', 'enum': ['top', 'bottom', 'left', 'right']},
                                           'end': {'type': 'number'}, 'on_structure': {'type': 'boolean'},
                                           'lift': {'type': 'number'}, 'sat': {'type': 'number'}, 'warm': {'type': 'number'}, 'clarity': {'type': 'number'}}}},
        'light_already_good': {'type': 'boolean', 'description': 'v1.2.1: informational only - the image model is always called; never means "edit lightly"'},
        'g_intent': {'type': 'string', 'description': 'English, 2-3 concrete light-and-colour intents for the image model, no numbers'},
        'params': {'type': 'object', 'additionalProperties': False,
                   'required': ['exposure_ev', 'contrast', 'highlights', 'shadows', 'clarity', 'vibrance', 'saturation', 'levels_black'],
                   'properties': {'exposure_ev': {'type': 'number'}, 'contrast': {'type': 'number'},
                                  'saturation': {'type': 'number'}, 'levels_black': {'type': 'number'},
                                  'highlights': {'type': 'number'}, 'shadows': {'type': 'number'},
                                  'clarity': {'type': 'number'}, 'vibrance': {'type': 'number'}}},
    },
}

# safe ranges for the N parameters the brief may set (grade.py units; n_grade.md)
PARAM_RANGES = {'exposure_ev': (-0.4, 0.4), 'contrast': (-0.2, 0.25), 'highlights': (-15, 5),
                'shadows': (-8, 12), 'clarity': (0.0, 0.25), 'vibrance': (-0.1, 0.4),
                'saturation': (0.85, 1.15), 'levels_black': (0.0, 12.0)}   # v1.0.9: haze needs a black point
NEUTRAL = {'saturation': 1.0}

PHYSICS = ('Follow real light physics: keep the existing light direction and time of day, shadows stay darker and cooler '
           'than sunlit areas, sky graded naturally, reflections dimmer than the objects, no added light sources, no halos. '
           'Do not add a spotlight or a glow around the subject; dark backgrounds stay as dark and clean as in the source.')

G_TEMPLATE = ('Edit the provided photo into a finished, professional-grade photograph with strong but natural photographic impact.\n'
              'Image A is the direct source photo. Keep the same framing, viewpoint and layout of everything in the scene.\n'
              'Make the light and colour work: {intent}.\n{physics}\n'
              'Natural photographic rendering: rich but believable colour, real depth and local contrast, clean highlights, '
              'shadows with detail. Keep the real glaze, glass and metal highlights and the existing light patches in the scene.\n'
              'Do not create a poster, collage or graphic design. Do not add text.{extra}')

# second G call after the first was rejected (v1.0.7): name what went wrong
RETRY_HINTS = {
    'scene': ' Keep exactly the same framing and every object in place; change only light and colour.',
    'darkening_patch': ' Do not darken the scene or the sky; keep the existing light.',
    'tone_order': ' Keep the brightness order of the scene: lit areas stay brighter than shade.',
    'light_shade_sep': ' Keep the separation between sunlit areas and shade.',
    'spotlight_glow': ' Do not add any glow or spotlight.',
    'removed_light': ' Keep every real light patch and highlight of the source.',
    'sky': ' Do not darken the sky.',
}


def brief_user_text(measure: dict) -> str:
    keep = {k: measure.get(k) for k in ('size', 'tone', 'colour', 'color', 'sky', 'attention', 'layout') if k in measure}
    return 'Measurements of the original (numbers only, they do not judge):\n' + json.dumps(keep, ensure_ascii=False)[:6000]


def clamp_brief(b: dict) -> dict:
    b = dict(b)
    p = dict(b.get('params') or {})
    for k, (lo, hi) in PARAM_RANGES.items():
        try:
            p[k] = round(min(hi, max(lo, float(p.get(k, NEUTRAL.get(k, 0.0))))), 4)
        except (TypeError, ValueError):
            p[k] = NEUTRAL.get(k, 0.0)
    lb = p.pop('levels_black', 0.0)   # grade.py takes the black point as levels.black
    if lb: p['levels'] = {'black': lb}
    b['params'] = p
    b['diagnoses'] = list(b.get('diagnoses') or [])
    keep = []   # v1.1.0: validated must-not-change regions; finish.py applies them through keep_regions.py
    for r in list(b.get('keep_regions') or [])[:6]:
        try:
            x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in r['box']]
        except (KeyError, TypeError, ValueError):
            continue
        if x1 - x0 >= 0.01 and y1 - y0 >= 0.01:
            keep.append({'what': str(r.get('what', ''))[:80], 'box': [x0, y0, x1, y1],
                         'mode': 'content' if r.get('mode') == 'content' else 'colour'})
    b['keep_regions'] = keep
    mv_out = []   # v1.2.0: validated improvement moves; finish.py grades them and improve_check.py checks they show
    LIM = {'lift': (-8.0, 8.0), 'sat': (0.8, 1.4), 'warm': (-4.0, 4.0), 'clarity': (0.0, 0.35)}
    for mv in list(b.get('moves') or [])[:4]:
        try:
            shape = mv.get('shape') if mv.get('shape') in ('gradient', 'rect', 'ellipse') else 'rect'
            q = {'what': str(mv.get('what', ''))[:80], 'look': str(mv.get('look', '')), 'shape': shape}
            if shape == 'gradient':
                q['from'] = mv.get('from') if mv.get('from') in ('top', 'bottom', 'left', 'right') else 'top'
                q['end'] = min(1.0, max(0.05, float(mv.get('end', 0.5))))
            else:
                x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in mv['box']]
                if x1 - x0 < 0.02 or y1 - y0 < 0.02: continue
                q['box'] = [x0, y0, x1, y1]; q['feather'] = 0.12
            if mv.get('on_structure'): q['on_structure'] = True
            for k, (lo, hi) in LIM.items():
                v = float(mv.get(k, 1.0 if k == 'sat' else 0.0))
                if v != (1.0 if k == 'sat' else 0.0): q[k] = min(hi, max(lo, v))
        except (KeyError, TypeError, ValueError):
            continue
        mv_out.append(q)
    b['moves'] = mv_out
    if mv_out:
        p['moves'] = mv_out
    if keep:
        p['keep'] = keep
    b['light_already_good'] = bool(b.get('light_already_good'))
    if b.get('genre') not in GENRES:
        b['genre'] = 'other'
    b['portrait'] = bool(b.get('portrait')) or b.get('genre') == 'portrait'
    b['g_intent'] = str(b.get('g_intent') or 'shape the light on the subject and give the scene natural depth')[:600]
    return b


def g_prompt(brief: dict, problems: list[str] | None = None) -> str:
    extra = ''.join(RETRY_HINTS[p] for p in (problems or []) if p in RETRY_HINTS)
    return G_TEMPLATE.format(intent=brief['g_intent'].rstrip('.'), physics=PHYSICS, extra=('\n' + extra.strip()) if extra else '')
