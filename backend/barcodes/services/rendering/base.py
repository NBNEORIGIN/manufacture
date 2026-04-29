from abc import ABC, abstractmethod
from dataclasses import dataclass
from django.conf import settings


@dataclass(frozen=True)
class LabelSpec:
    """Physical + content spec for a single label. Printer-agnostic."""
    barcode_value: str
    label_title: str
    condition: str = "New"
    # Physical dimensions — SHOULD be sourced from settings via build_spec_from_settings().
    # The defaults below are development fallbacks only, never trust them in production code.
    width_mm: float = 50.0
    height_mm: float = 25.0
    dpi: int = 203


def build_spec_from_settings(
    barcode_value: str,
    label_title: str,
    condition: str = "New",
    *,
    width_mm: float | None = None,
    height_mm: float | None = None,
    dpi: int | None = None,
) -> LabelSpec:
    """
    Construct a LabelSpec with physical dimensions sourced from settings,
    with optional per-call overrides for printer-specific dimensions.

    Pass width_mm/height_mm/dpi when rendering for a specific Printer record;
    omit them to fall back to the global LABEL_* settings (legacy default).
    """
    return LabelSpec(
        barcode_value=barcode_value,
        label_title=label_title,
        condition=condition,
        width_mm=width_mm if width_mm is not None else settings.LABEL_WIDTH_MM,
        height_mm=height_mm if height_mm is not None else settings.LABEL_HEIGHT_MM,
        dpi=dpi if dpi is not None else settings.LABEL_DPI,
    )


class LabelRenderer(ABC):
    """Abstract base for printer command language renderers."""

    @property
    @abstractmethod
    def content_type(self) -> str:
        """e.g. 'application/zpl', 'application/tspl'. For logging/debugging."""

    @abstractmethod
    def render(self, spec: LabelSpec, quantity: int = 1) -> str:
        """Render a LabelSpec + quantity into a printer-ready command string."""
