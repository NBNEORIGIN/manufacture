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
) -> LabelSpec:
    """
    Construct a LabelSpec with physical dimensions sourced from Django settings.

    This is the ONLY correct way to build a LabelSpec in production code.
    Never rely on the dataclass defaults — always go through this helper so
    that changing LABEL_WIDTH_MM / LABEL_HEIGHT_MM / LABEL_DPI in settings
    actually takes effect.
    """
    return LabelSpec(
        barcode_value=barcode_value,
        label_title=label_title,
        condition=condition,
        width_mm=settings.LABEL_WIDTH_MM,
        height_mm=settings.LABEL_HEIGHT_MM,
        dpi=settings.LABEL_DPI,
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
