import requests
from django.conf import settings
from .base import LabelSpec


def render_preview_png(command_string: str, spec: LabelSpec) -> bytes:
    """
    POST a rendered command string to Labelary, return PNG bytes.
    Only supports ZPL input. Raises if LABEL_COMMAND_LANGUAGE != 'zpl'.
    """
    if getattr(settings, 'LABEL_COMMAND_LANGUAGE', 'zpl') != 'zpl':
        raise RuntimeError("Preview currently only supported for ZPL")

    dpmm = spec.dpi // 25  # 203 dpi → 8 dpmm
    width_in = spec.width_mm / 25.4
    height_in = spec.height_mm / 25.4
    base = settings.LABELARY_API_BASE.rstrip('/')
    url = (
        f"{base}/printers/{dpmm}dpmm/labels/"
        f"{width_in:.2f}x{height_in:.2f}/0/"
    )
    response = requests.post(
        url,
        data=command_string.encode('utf-8'),
        headers={'Accept': 'image/png'},
        timeout=5,
    )
    response.raise_for_status()
    return response.content
