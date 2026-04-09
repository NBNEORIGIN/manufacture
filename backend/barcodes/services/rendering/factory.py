from django.conf import settings
from .base import LabelRenderer
from .zpl import ZplLabelRenderer
from .tspl import TsplLabelRenderer


def get_renderer() -> LabelRenderer:
    lang = getattr(settings, 'LABEL_COMMAND_LANGUAGE', 'zpl').lower()
    if lang == 'zpl':
        return ZplLabelRenderer()
    if lang == 'tspl':
        return TsplLabelRenderer()
    raise ValueError(f"Unknown LABEL_COMMAND_LANGUAGE: {lang}")
