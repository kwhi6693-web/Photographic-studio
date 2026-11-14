from .base import ImageEditor, NotConfigured, ProviderError, Usage, VisionModel


def make_vision(cfg, engine_cfg):
    name = cfg.name
    if name == 'replay':
        from .replay import ReplayVision
        return ReplayVision(cfg.extra.get('replay_dir') or engine_cfg.replay_dir)
    from .http_models import GeminiVision, OpenAIVision
    if name == 'openai': return OpenAIVision(cfg, engine_cfg.timeout_s)
    if name == 'gemini': return GeminiVision(cfg, engine_cfg.timeout_s)
    raise NotConfigured(f'unknown vision provider {name!r}')


def make_editor(cfg, engine_cfg):
    name = cfg.name
    if name == 'replay':
        from .replay import ReplayEditor
        return ReplayEditor(cfg.extra.get('replay_dir') or engine_cfg.replay_dir)
    from .http_models import GeminiEditor, OpenAIEditor
    if name == 'openai': return OpenAIEditor(cfg, engine_cfg.timeout_s)
    if name == 'gemini': return GeminiEditor(cfg, engine_cfg.timeout_s)
    raise NotConfigured(f'unknown editor provider {name!r}')
