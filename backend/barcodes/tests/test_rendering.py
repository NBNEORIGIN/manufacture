import pytest
from unittest.mock import patch
from django.test import override_settings
from barcodes.services.rendering.base import LabelSpec, build_spec_from_settings, LabelRenderer
from barcodes.services.rendering.zpl import ZplLabelRenderer
from barcodes.services.rendering.tspl import TsplLabelRenderer
from barcodes.services.rendering.factory import get_renderer


# --- LabelSpec ---

def test_labelspec_is_frozen():
    spec = LabelSpec(barcode_value='X001TEST001', label_title='Test Product')
    with pytest.raises((AttributeError, TypeError)):
        spec.barcode_value = 'other'  # type: ignore[misc]


def test_labelspec_is_hashable():
    spec = LabelSpec(barcode_value='X001TEST001', label_title='Test')
    assert hash(spec) is not None
    s = {spec}
    assert spec in s


# --- Factory ---

@override_settings(LABEL_COMMAND_LANGUAGE='zpl')
def test_factory_returns_zpl_renderer():
    assert isinstance(get_renderer(), ZplLabelRenderer)


@override_settings(LABEL_COMMAND_LANGUAGE='tspl')
def test_factory_returns_tspl_renderer():
    assert isinstance(get_renderer(), TsplLabelRenderer)


@override_settings(LABEL_COMMAND_LANGUAGE='bogus')
def test_factory_raises_for_unknown_language():
    with pytest.raises(ValueError, match='Unknown label command language'):
        get_renderer()


def test_factory_explicit_language_overrides_setting():
    """Per-printer override: explicit language arg wins over LABEL_COMMAND_LANGUAGE."""
    with override_settings(LABEL_COMMAND_LANGUAGE='zpl'):
        assert isinstance(get_renderer('tspl'), TsplLabelRenderer)
        assert isinstance(get_renderer('zpl'), ZplLabelRenderer)


# --- TSPL renderer ---

def test_tspl_render_emits_minimal_program():
    renderer = TsplLabelRenderer()
    spec = LabelSpec(
        barcode_value='X001TEST001',
        label_title='Test Product Title',
        condition='New',
        width_mm=50,
        height_mm=25,
        dpi=203,
    )
    out = renderer.render(spec, quantity=3)
    # Sanity: every TSPL program must contain SIZE / CLS / PRINT, and our
    # payload must include the barcode value.
    assert 'SIZE 50 mm,25 mm' in out
    assert 'CLS' in out
    assert 'PRINT 3,1' in out
    assert 'X001TEST001' in out
    # CRLF line endings — most TSPL printers tolerate \n but the spec is CRLF.
    assert out.endswith('\r\n')


# --- ZPL renderer ---

def _spec(**kwargs) -> LabelSpec:
    defaults = dict(barcode_value='X001TEST001', label_title='Test Product Title', condition='New',
                    width_mm=50.0, height_mm=25.0, dpi=203)
    defaults.update(kwargs)
    return LabelSpec(**defaults)


def test_zpl_render_happy_path():
    renderer = ZplLabelRenderer()
    zpl = renderer.render(_spec(), quantity=1)
    assert zpl.startswith('^XA')
    assert zpl.endswith('^XZ')
    assert 'X001TEST001' in zpl


def test_zpl_render_xz_balanced():
    renderer = ZplLabelRenderer()
    zpl = renderer.render(_spec(), quantity=5)
    assert zpl.count('^XA') == 1
    assert zpl.count('^XZ') == 1


def test_zpl_quantity_directive():
    renderer = ZplLabelRenderer()
    zpl = renderer.render(_spec(), quantity=42)
    assert '^PQ42,' in zpl


def test_zpl_title_truncation():
    renderer = ZplLabelRenderer()
    long_title = 'A' * 200
    spec = _spec(label_title=long_title, width_mm=50.0)
    zpl = renderer.render(spec)
    # The title in the ZPL should not contain 200 A's — it was truncated
    assert 'A' * 200 not in zpl


def test_zpl_special_chars_survive():
    renderer = ZplLabelRenderer()
    # These should not crash the renderer (^CI28 handles UTF-8)
    spec = _spec(label_title='Café résumé £5 über')
    zpl = renderer.render(spec)
    assert '^XZ' in zpl


def test_zpl_reserved_chars_escaped_in_title():
    renderer = ZplLabelRenderer()
    spec = _spec(label_title='A^B~C\\D', condition='New^')
    zpl = renderer.render(spec)
    # Unescaped ^ and ~ outside of command positions would corrupt ZPL
    # After field data starts (^FD), any ^ should be \^
    # We check the escape method directly
    assert ZplLabelRenderer._escape('^') == '\\^'
    assert ZplLabelRenderer._escape('~') == '\\~'
    assert ZplLabelRenderer._escape('\\') == '\\\\'


def test_zpl_dimensions_scale_50x25():
    renderer = ZplLabelRenderer()
    spec = _spec(width_mm=50.0, height_mm=25.0, dpi=203)
    zpl = renderer.render(spec)
    # 50mm * 203 / 25.4 = 399 dots (floor)
    assert '^PW399' in zpl
    assert '^LL199' in zpl


def test_zpl_dimensions_scale_67x25():
    renderer = ZplLabelRenderer()
    spec = _spec(width_mm=67.0, height_mm=25.0, dpi=203)
    zpl = renderer.render(spec)
    # 67mm * 203 / 25.4 = 535 dots
    assert '^PW535' in zpl
    assert '^LL199' in zpl


# --- build_spec_from_settings ---

@override_settings(LABEL_WIDTH_MM=60.0, LABEL_HEIGHT_MM=30.0, LABEL_DPI=300)
def test_build_spec_from_settings_uses_settings_values():
    spec = build_spec_from_settings('X001TEST001', 'Title', 'New')
    assert spec.width_mm == 60.0
    assert spec.height_mm == 30.0
    assert spec.dpi == 300
