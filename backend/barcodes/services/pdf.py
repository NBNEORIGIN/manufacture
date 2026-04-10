"""
Generate a printable A4 PDF for Avery 27-up label sheets (default: L4791, 3×9).

All sheet dimensions are read from Django settings so we can adjust for a
different Avery template without touching this file.

Usage:
    from barcodes.services.pdf import generate_label_pdf
    pdf_bytes = generate_label_pdf([
        {'barcode_value': 'X001TEST001', 'label_title': 'My Product', 'condition': 'New', 'quantity': 3},
        ...
    ])
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


def generate_label_pdf(items: list[dict]) -> bytes:
    """
    Render labels onto A4 pages in Avery 27-up grid layout.

    items: list of dicts with keys:
        barcode_value (str)
        label_title   (str)
        condition     (str, default 'New')
        quantity      (int, default 1)

    Returns raw PDF bytes.
    """
    # Expand each item by its quantity into a flat list of labels
    labels: list[dict] = []
    for item in items:
        qty = max(1, int(item.get('quantity', 1)))
        for _ in range(qty):
            labels.append(item)

    if not labels:
        raise ValueError("No labels to render")

    cfg = _sheet_config()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4

    labels_per_page = cfg['cols'] * cfg['rows']
    idx = 0

    while idx < len(labels):
        for row in range(cfg['rows']):
            for col in range(cfg['cols']):
                if idx >= len(labels):
                    break
                x = cfg['left_margin'] + col * (cfg['label_w'] + cfg['h_gap'])
                # ReportLab y=0 is bottom of page; labels fill top-down
                y = (page_h
                     - cfg['top_margin']
                     - (row + 1) * cfg['label_h']
                     - row * cfg['v_gap'])
                _draw_label(c, x, y, cfg['label_w'], cfg['label_h'], labels[idx])
                idx += 1
            if idx >= len(labels):
                break

        if idx < len(labels):
            c.showPage()

    c.save()
    return buf.getvalue()


def _draw_label(c: canvas.Canvas, x: float, y: float, w: float, h: float, label: dict) -> None:
    """Draw one label at bottom-left corner (x, y) with size (w × h) in points."""
    barcode_value = label.get('barcode_value', '')
    label_title = label.get('label_title', '')
    condition = label.get('condition', 'New')

    # --- Barcode ---
    bc_height = h * 0.48
    try:
        bc = code128.Code128(barcode_value, barHeight=bc_height, barWidth=0.9)
        bc_w = bc.width
        bc_x = x + (w - bc_w) / 2
        bc_y = y + h * 0.40
        bc.drawOn(c, bc_x, bc_y)
    except Exception:
        # If the barcode value is invalid, draw a placeholder box
        c.rect(x + 4 * mm, y + h * 0.40, w - 8 * mm, bc_height)

    # --- Barcode string ---
    c.setFont('Helvetica', 7)
    c.drawCentredString(x + w / 2, y + h * 0.29, barcode_value)

    # --- Product title (word-wrapped to 2 lines max) ---
    title_lines = textwrap.wrap(label_title, width=32)[:2]
    c.setFont('Helvetica', 6.5)
    if len(title_lines) == 2:
        c.drawCentredString(x + w / 2, y + h * 0.20, title_lines[0])
        c.drawCentredString(x + w / 2, y + h * 0.12, title_lines[1])
    elif title_lines:
        c.drawCentredString(x + w / 2, y + h * 0.16, title_lines[0])

    # --- Condition ---
    c.setFont('Helvetica', 6)
    c.drawCentredString(x + w / 2, y + h * 0.05, condition)
