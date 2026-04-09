import textwrap
from .base import LabelRenderer, LabelSpec


class ZplLabelRenderer(LabelRenderer):
    content_type = 'application/zpl'

    def render(self, spec: LabelSpec, quantity: int = 1) -> str:
        width_dots = int(spec.width_mm * spec.dpi / 25.4)
        height_dots = int(spec.height_mm * spec.dpi / 25.4)

        # Barcode occupies top ~58% of label height
        bc_height = int(height_dots * 0.58)

        # Title character width budget: rough calculation based on label width
        # At 203 dpi, font 0 at size 22 ≈ 12 dots/char → ~30 chars fit in 400 dots
        char_budget = max(10, int((width_dots - 60) / 13))
        truncated_title = textwrap.shorten(
            spec.label_title, width=char_budget, placeholder='…'
        )

        safe_title = self._escape(truncated_title)
        safe_condition = self._escape(spec.condition)

        zpl = (
            f"^XA"
            f"^PW{width_dots}"
            f"^LL{height_dots}"
            f"^CI28"
            f"^FO30,15^BY2,2.5,{bc_height}"
            f"^BCN,{bc_height},N,N,N"
            f"^FD{spec.barcode_value}^FS"
            f"^FO30,{bc_height + 25}^A0N,22,22^FD{spec.barcode_value}^FS"
            f"^FO30,{bc_height + 50}^A0N,22,22"
            f"^FB{width_dots - 60},1,0,L,0^FD{safe_title}^FS"
            f"^FO30,{bc_height + 75}^A0N,18,18^FD{safe_condition}^FS"
            f"^PQ{quantity},0,1,Y"
            f"^XZ"
        )
        return zpl

    @staticmethod
    def _escape(text: str) -> str:
        """Escape ZPL reserved characters: ^, ~, \\"""
        return text.replace('\\', '\\\\').replace('^', '\\^').replace('~', '\\~')
