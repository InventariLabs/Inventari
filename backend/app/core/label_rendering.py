"""Label-rendering registry — inversion of the Core → printing dependency.

Rendering a label to PNG is owned by the ``printing`` module: it holds the
layout rules, the QR generation and the Pillow dependency. Core endpoints
(`/labels`, storage label download) still need to produce those images, but
Core must never import a feature module — the isolation lint exists to keep
that direction one-way.

So printing *registers* its renderers here at startup and Core calls them
through this registry, the same shape as :mod:`app.core.period_guard`.

Unlike the period guard, absence is not a no-op: a request that asks for a
label image cannot be answered without a renderer, so the callers raise
:class:`LabelRendererUnavailableError` and map it to a 503. Silently returning
nothing would look like a corrupt image to the client.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

SingleRendererFn = Callable[..., bytes]
BatchRendererFn = Callable[..., bytes]


class LabelRendererUnavailableError(RuntimeError):
    """No renderer registered — the printing module is absent or was rejected."""


_single: SingleRendererFn | None = None
_batch: BatchRendererFn | None = None


def register_label_renderers(
    *,
    single: SingleRendererFn,
    batch: BatchRendererFn,
) -> None:
    """Register the PNG renderers (called by the printing module at startup)."""
    global _single, _batch
    _single = single
    _batch = batch


def clear_label_renderers() -> None:
    """Reset the registry — test isolation only."""
    global _single, _batch
    _single = None
    _batch = None


def render_label_png(label: Any, **kwargs: Any) -> bytes:
    """Render one label to PNG via the registered renderer."""
    if _single is None:
        raise LabelRendererUnavailableError(
            'Label rendering requires the printing module, which is not available.'
        )
    return _single(label, **kwargs)


def render_label_batch_png(labels: Sequence[Any], **kwargs: Any) -> bytes:
    """Render a sheet of labels to PNG via the registered renderer."""
    if _batch is None:
        raise LabelRendererUnavailableError(
            'Label rendering requires the printing module, which is not available.'
        )
    return _batch(labels, **kwargs)
