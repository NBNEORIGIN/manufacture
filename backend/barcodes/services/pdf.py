"""
Generate a printable PDF of barcode labels.

Two output formats are supported:

* ``avery`` (default) — A4 pages laid out as an Avery 27-up grid (default
  template L4791, 3×9). For laser/inkjet printing onto sticker sheets.
* ``roll`` — one label per page, page size = label size (default 50×25mm).
  For continuous-roll thermal printers fed via the OS print dialog.

Both modes call ``_draw_label`` to render an individual label.

Usage::

    from barcodes.services.pdf import generate_label_pdf
    pdf_bytes = generate_label_pdf([
        {'barcode_value': 'X001TEST001', 'label_title': 'My Product',
         'condition': 'New', 'quantity': 3},
        ...
    ], format='roll')
"""
import textwrap
from io import BytesIO

from django.conf import settings
from reportlab.graphics.barcode import code128
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def _sheet_config():
    return {
        'cols': settings.AVERY_COLS,
        'rows': settings.AVERY_ROWS,
        'label_w': settings.AVERY_LABEL_W_MM * mm,
        'label_h': settings.AVERY_LABEL_H_MM * mm,
        'top_margin': settings.AVERY_TOP_MARGIN_MM * mm,
        'left_margin': settings.AVERY_LEFT_MARGIN_MM * mm,
        'h_gap': settings.AVERY_H_GAP_MM * mm,
        'v_gap': settings.AVERY_V_GAP_MM * mm,
    }


def _roll_dims_mm() -> tuple[float, float]:
    """Roll label dimensions in mm — overrideable via settings."""
    w = float(getattr(settings, 'ROLL_LABEL_W_MM', 50.0))
    h = float(getattr(settings, 'ROLL_LABEL_H_MM', 25.0))
    return w, h


def generate_label_pdf(
    items: list[dict],
    new_page_per_item: bool = True,
    format: str = 'avery',
) -> bytes:
    """
    Render labels onto a PDF.

    items: list of dicts with keys:
        barcode_value (str)
        label_title   (str)
        condition     (str, default 'New')
        quantity      (int, default 1)

    new_page_per_item: Avery only — if True (default), each SKU starts on a
        fresh sheet so shipments can be kept separate. Ignored in roll mode
        because every label is its own page anyway.

    format: 'avery' for A4 27-up, 'roll' for one-label-per-page.

    Returns raw PDF bytes.
    """
    if not items:
        raise ValueError("No items to render")

    if format == 'roll':
        return _generate_roll_pdf(items)
    if format != 'avery':
        raise ValueError(f"Unknown PDF format: {format!r}. Use 'avery' or 'roll'.")

    cfg = _sheet_config()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4

    def draw_batch(batch: list[dict]) -> None:
        """Pack a batch of labels contiguously, starting from the top-left of the current page."""
        idx = 0
        while idx < len(batch):
            for row in range(cfg['rows']):
                for col in range(cfg['cols']):
                    if idx >= len(batch):
                        break
                    x = cfg['left_margin'] + col * (cfg['label_w'] + cfg['h_gap'])
                    y = (page_h
                         - cfg['top_margin']
                         - (row + 1) * cfg['label_h']
                         - row * cfg['v_gap'])
                    _draw_label(c, x, y, cfg['label_w'], cfg['label_h'], batch[idx])
                    idx += 1
                if idx >= len(batch):
                    break
            if idx < len(batch):
                c.showPage()

    if new_page_per_item:
        # Each SKU gets its own sheet(s). A 30-label job for SKU A and a
        # 2-label job for SKU B result in two separate PDFs stitched together.
        for i, item in enumerate(items):
            qty = max(1, int(item.get('quantity', 1)))
            batch = [item] * qty
            if i > 0:
                c.showPage()  # start this SKU on a fresh sheet
            draw_batch(batch)
    else:
        # Legacy contiguous packing
        labels: list[dict] = []
        for item in items:
            qty = max(1, int(item.get('quantity', 1)))
            labels.extend([item] * qty)
        draw_batch(labels)

    c.save()
    return buf.getvalue()


def _draw_label(c: canvas.Canvas, x: float, y: float, w: float, h: float, label: dict) -> None:
    """Draw one label at bottom-left corner (x, y) with size (w × h) in points.

    Layout from top to bottom:
        M-number (bold)
        Code128 barcode
        Barcode value
        Product title (1-2 lines, word-wrapped)
        Condition

    Fonts are deliberately on the small side so titles like "Silver Circular
    Push Pull" fit within the print head's printable area on the PM-2411-BT
    (~46mm of 50.8mm media). Wrapping width of 28 chars also guards against
    near-edge clipping that drawCentredString can hit when text is wider than
    the imageable region.
    """
    barcode_value = label.get('barcode_value', '')
    label_title = label.get('label_title', '')
    condition = label.get('condition', 'New')
    m_number = label.get('m_number', '')

    # --- M-number (top, bold) ---
    if m_number:
        c.setFont('Helvetica-Bold', 8)
        c.drawCentredString(x + w / 2, y + h * 0.85, m_number)

    # --- Barcode ---
    bc_height = h * 0.36
    try:
        bc = code128.Code128(barcode_value, barHeight=bc_height, barWidth=0.75)
        bc_w = bc.width
        bc_x = x + (w - bc_w) / 2
        bc_y = y + h * 0.44
        bc.drawOn(c, bc_x, bc_y)
    except Exception:
        # If the barcode value is invalid, draw a placeholder box
        c.rect(x + 4 * mm, y + h * 0.44, w - 8 * mm, bc_height)

    # --- Barcode string ---
    c.setFont('Helvetica', 6)
    c.drawCentredString(x + w / 2, y + h * 0.34, barcode_value)

    # --- Product title (word-wrapped to 2 lines max) ---
    title_lines = textwrap.wrap(label_title, width=28)[:2]
    c.setFont('Helvetica', 6)
    if len(title_lines) == 2:
        c.drawCentredString(x + w / 2, y + h * 0.22, title_lines[0])
        c.drawCentredString(x + w / 2, y + h * 0.13, title_lines[1])
    elif title_lines:
        c.drawCentredString(x + w / 2, y + h * 0.18, title_lines[0])

    # --- Condition ---
    c.setFont('Helvetica', 5.5)
    c.drawCentredString(x + w / 2, y + h * 0.04, condition)


def _generate_roll_pdf(items: list[dict]) -> bytes:
    """
    One label per page. Page size = label size (default 50×25mm).

    Designed for continuous-roll thermal printers (e.g. PM-2411-BT) fed via
    the OS print dialog — the printer pulls one label per page, no margins,
    no sheet alignment. Same per-label visual layout as Avery mode (barcode,
    title, condition) so the staff workflow stays identical.

    Quantity: each item is repeated ``quantity`` times — one page each.
    """
    label_w_mm, label_h_mm = _roll_dims_mm()
    label_w = label_w_mm * mm
    label_h = label_h_mm * mm

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(label_w, label_h))

    for item in items:
        qty = max(1, int(item.get('quantity', 1)))
        for _ in range(qty):
            _draw_label(c, 0, 0, label_w, label_h, item)
            c.showPage()

    c.save()
    return buf.getvalue()
