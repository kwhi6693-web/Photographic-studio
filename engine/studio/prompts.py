"""What the vision model is asked, and how the G prompt is built. Both come from the skill's own references, so the
engine and the ChatGPT skill judge by the same rules."""
import json
from .config import REPO

REF = REPO / 'photographic-studio' / 'references'

# grade.py parameters the brief may set (regions are left out in the engine: they need eyes on positions)
PARAM_RANGES = {
    'exposure_ev': (-1.0, 1.0), 'contrast': (-0.5, 0.6), 'highlights': (-25, 25), 'shadows': (-25, 25),
    'clarity': (0.0, 0.6), 'saturation': (0.0, 1.6), 'vibrance': (-0.5, 0.8),
}
GENRES = ('day', 'night', 'lowcolour', 'museum')

PHYSICS = ('Follow real light physics: keep the existing light direction and time of day, shadows stay darker and cooler '
           'than sunlit areas, sky graded naturally, reflections dimmer than the objects, no added light sources, no halos. '
           'Do not add a spotlight or a glow around the subject; dark backgrounds stay as dark and clean as in the source.')


def _ref(name, limit=7000):
    p = REF / name
    return p.read_text(encoding='utf-8')[:limit] if p.exists() else ''


def reading_prompt(measure: dict) -> str:
    return f"""You are the photo reader and director of Photographic Studio, a one-tap editor for non-portrait photos.
Read the attached photo like a photographer, then write the director brief. Rules (from the project's own references):

=== director_brief.md ===
{_ref('director_brief.md')}
=== end ===

Objective measurements of the photo (numbers only, read them next to the image):
{json.dumps(measure, ensure_ascii=False)[:3000]}

Answer with ONE JSON object and nothing else:
{{
  "is_portrait": false,            // true if people are the main subject: the engine then refuses
  "genre": "day|night|lowcolour|museum",   // museum = museums, showcases, dark-background still life
  "story_style": "...", "subject": "...", "tone": "...", "colour": "...", "keep": "...",   // the brief, one line each, Chinese
  "g_intent": "2-3 concrete photographic intents in English, about light and colour only, no numbers",
  "params": {{ "clarity": 0.1, "vibrance": 0.15 }}   // grade.py parameters for N; allowed keys and ranges: {json.dumps(PARAM_RANGES)}
}}"""


def g_prompt(intent: str, correction: str = '') -> str:
    extra = f"\n{correction}" if correction else ''
    return ("Edit the provided photo into a finished, professional-grade photograph with strong but natural photographic impact.\n"
            "Image A is the direct source photo. Keep the same framing, viewpoint and layout of everything in the scene.\n"
            f"Make the light and colour work: {intent.strip()}.\n{PHYSICS}\n"
            "Keep the real glaze, glass and metal highlights and the existing light patches in the scene.\n"
            "Natural photographic rendering: rich but believable colour, real depth and local contrast, clean highlights, "
            "shadows with detail.\nDo not create a poster, collage or graphic design. Do not add text." + extra)


# what to tell G the second time, from the problems finish.py found on the G routes (SKILL step 5, v1.0.7)
CORRECTIONS = {
    'darkening_patch': 'Do not darken any part of the scene that was lit in the source.',
    'tone_order': 'Keep the brightness order of the scene: what is bright in the source stays brighter than what is dark.',
    'light_shade_sep': 'Keep the separation between sunlit areas and shade exactly as in the source.',
    'spotlight_glow': 'Do not add any new light, spotlight or glow.',
    'L_mean_change': 'Do not darken the photo overall; keep or slightly raise its brightness.',
    'sky_L_change': 'Do not darken the sky; keep its brightness and natural gradient.',
    'chroma_ratio': 'Keep the colours believable; do not oversaturate.',
}


def correction_for(problems) -> str:
    lines = [CORRECTIONS[p] for p in problems if p in CORRECTIONS]
    lines.append('Concentrate the light and colour on the main subject instead.')
    return ' '.join(dict.fromkeys(lines))


def clean_params(p: dict) -> dict:
    out = {}
    for k, (lo, hi) in PARAM_RANGES.items():
        if isinstance(p.get(k), (int, float)): out[k] = max(lo, min(hi, float(p[k])))
    wb = p.get('white_balance')
    if isinstance(wb, dict):
        out['white_balance'] = {k: max(-1.0, min(1.0, float(wb[k]))) for k in ('temp', 'tint') if isinstance(wb.get(k), (int, float))}
    return out
