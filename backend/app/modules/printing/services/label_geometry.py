"""How many pixels a label is: one rule for every label and every printer.

A label W x H mm is drawn as W x H mm, at ``LABEL_DPI``. That file is what
the download gives, what the preview shows and what a print job carries, so
the three cannot disagree about the size of a label.

It used to depend on a named media profile, and the tape profile cropped the
label to its content, drew only the cassette's printable strip and snapped
its height to the raster a Brother expects. A 50 x 24 label then had four
sizes at once: the settings, the file (12 x 18 mm), the preview (that file
stretched to 24 mm) and the tape (38 x 24 mm with the printer's blank lead).
Fitting a label to a printer is now the job of the print agent next to it.

The agent may still ask for the same label at its own raster, ``dpi`` and at
most ``max_height_px`` tall, so a 180 dpi head gets QR modules that land on
whole dots instead of a 300 dpi file resampled into uneven ones. The layout
in millimetres stays the same; a label taller than the head can print is
scaled down as a whole, and ``scale`` says by how much.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ['LABEL_DPI', 'Raster', 'raster_for']

#: The resolution a label file is drawn at. An office printer prints 300 or
#: 600 dpi; a label printer's driver resamples to its own, and the agent can
#: ask for the label at that resolution instead (see ``raster_for``).
LABEL_DPI = 300

#: The fewest pixels a side may have, however small the label or raster.
_MIN_PX = 8


@dataclass(frozen=True)
class Raster:
    """A label's size in pixels on one raster."""

    width_px: int
    height_px: int
    #: Pixels per millimetre of label actually drawn: every size on the label
    #: is a number of millimetres multiplied by this.
    px_per_mm: float
    #: The drawn label as a share of its real size: 1.0 unless the raster was
    #: too short for it and it had to be scaled down to fit.
    scale: float
    #: The resolution the file states: the raster's own, so a driver prints
    #: the pixels at the size they were drawn for. A shrunk label states it
    #: too, not ``px_per_mm`` in inches, which would stretch it back to the
    #: label's full size on any driver that honours it.
    dpi: float


def raster_for(
    width_mm: float,
    height_mm: float,
    dpi: float = LABEL_DPI,
    max_height_px: int | None = None,
) -> Raster:
    """The pixels a W x H mm label takes at ``dpi``, no taller than allowed."""
    px_per_mm = dpi / 25.4
    scale = 1.0
    natural_height = height_mm * px_per_mm
    if max_height_px is not None and natural_height > max_height_px:
        scale = max_height_px / natural_height
        px_per_mm *= scale
    return Raster(
        width_px=max(_MIN_PX, round(width_mm * px_per_mm)),
        height_px=max(_MIN_PX, round(height_mm * px_per_mm)),
        px_per_mm=px_per_mm,
        scale=scale,
        dpi=dpi,
    )
