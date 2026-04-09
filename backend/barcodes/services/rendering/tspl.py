from .base import LabelRenderer, LabelSpec


class TsplLabelRenderer(LabelRenderer):
    content_type = 'application/tspl'

    def render(self, spec: LabelSpec, quantity: int = 1) -> str:
        raise NotImplementedError(
            "TSPL renderer not implemented. Set LABEL_COMMAND_LANGUAGE=zpl "
            "or implement this renderer when switching to a TSPL-only printer."
        )
