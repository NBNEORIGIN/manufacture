from django.conf import settings
from .base import LabelRenderer
from .zpl import ZplLabelRenderer
from .tspl import TsplLabelRenderer


def get_renderer(language: str | None = None) -> LabelRenderer:
    """
    Resolve a renderer for the given language. Falls back to the
    LABEL_COMMAND_LANGUAGE setting when no language is supplied.
    """
    lang = (language or getattr(settings, 'LABEL_COMMAND_LANGUAGE', 'zpl')).lower()
    if lang == 'zpl':
        return ZplLabelRenderer()
    if lang == 'tspl':
        return TsplLabelRenderer()
    raise ValueError(f"Unknown label command language: {lang}")
