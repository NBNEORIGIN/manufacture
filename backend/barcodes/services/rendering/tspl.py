"""
TSPL (TSC Printer Language) renderer.

TSPL is the command language used by TSC, Postek and many compatible
small thermal label printers (the PM-2411-BT etc.). Each TSPL command is a
keyword followed by arguments and ends with CRLF. A label is built by
SIZE → GAP → CLS → drawing commands → PRINT.

This renderer outputs a single-label program that the agent can pipe over
serial / Bluetooth or TCP to the printer. Quantity is handled by the
final `PRINT n,1` directive (n labels, 1 copy each).

Reference dialects we target by default — the PM-2411-BT family at 203 dpi:
  - SIZE in millimetres
  - GAP between labels: 2 mm (printer auto-detects on most models)
  - DENSITY: 8  (mid-range; tune up if the print is too faint)
  - SPEED: 4
  - DIRECTION: 1
  - Code 128 barcode via `BARCODE`
  - Bitmap font 3 / size 1 for Latin text
"""
from .base import LabelRenderer, LabelSpec


def _truncate(text: str, max_chars: int) -> str:
    text = text or ''
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + '…'


class TsplLabelRenderer(LabelRenderer):
    content_type = 'application/tspl'

    def render(self, spec: LabelSpec, quantity: int = 1) -> str:
        # TSPL works in dots — same conversion as ZPL: dots = mm × dpi / 25.4.
        # Keep dimensions in mm in the SIZE command; positions still need dots.
        dpmm = spec.dpi / 25.4
        width_dots = int(round(spec.width_mm * dpmm))
        height_dots = int(round(spec.height_mm * dpmm))

        # Layout — keeps the label readable at 50 × 25 mm:
        #   top 50% : Code-128 barcode
        #   below   : barcode value (text), label title (truncated), condition
        bar_h_dots = max(40, int(height_dots * 0.55))
        bar_x = max(10, int(width_dots * 0.06))
        bar_y = max(10, int(height_dots * 0.08))

        text_x = bar_x
        text_y_value = bar_y + bar_h_dots + 4
        text_y_title = text_y_value + 22
        text_y_cond = text_y_title + 22

        # Title truncation — rough rule-of-thumb for the 50mm width at 203dpi
        # using font "3" which is ~12pt. ~30 chars fit on a 50mm line.
        max_title_chars = max(10, int((spec.width_mm / 50.0) * 30))
        title = _truncate(spec.label_title, max_title_chars)
        condition = (spec.condition or '').strip()

        # Bar height for embedded text: 0 = no human-readable, 2 = below.
        # We emit our own text below the barcode for finer placement.
        commands = [
            f'SIZE {spec.width_mm} mm,{spec.height_mm} mm',
            'GAP 2 mm,0 mm',
            'DIRECTION 1',
            'DENSITY 8',
            'SPEED 4',
            'CLS',
            f'BARCODE {bar_x},{bar_y},"128",{bar_h_dots},0,0,2,2,"{spec.barcode_value}"',
            f'TEXT {text_x},{text_y_value},"3",0,1,1,"{spec.barcode_value}"',
            f'TEXT {text_x},{text_y_title},"3",0,1,1,"{title}"',
        ]
        if condition:
            commands.append(f'TEXT {text_x},{text_y_cond},"3",0,1,1,"{condition}"')
        commands.append(f'PRINT {quantity},1')
        # TSPL expects each command terminated with CRLF.
        return '\r\n'.join(commands) + '\r\n'
