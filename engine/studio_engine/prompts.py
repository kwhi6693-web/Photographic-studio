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
- If people's faces/bodies are the main subject, set portrait=true (the service does not retouch portraits).
Return ONLY JSON matching the schema. Use the measurements as evidence; trust your eyes when they disagree."""

BRIEF_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['story', 'subject', 'genre', 'portrait', 'diagnoses', 'keep', 'g_intent', 'params'],
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
    if b.get('genre') not in GENRES:
        b['genre'] = 'other'
    b['portrait'] = bool(b.get('portrait')) or b.get('genre') == 'portrait'
    b['g_intent'] = str(b.get('g_intent') or 'shape the light on the subject and give the scene natural depth')[:600]
    return b


def g_prompt(brief: dict, problems: list[str] | None = None) -> str:
    extra = ''.join(RETRY_HINTS[p] for p in (problems or []) if p in RETRY_HINTS)
    return G_TEMPLATE.format(intent=brief['g_intent'].rstrip('.'), physics=PHYSICS, extra=('\n' + extra.strip()) if extra else '')
