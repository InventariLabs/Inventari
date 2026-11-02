"""What a storage location's label says.

Shared by the label endpoint, which renders it on request, and by the print
queue, which freezes it when a label is sent to a printer — so a label printed
either way carries the same text.
"""

from typing import Any


def label_shows_description(storage: Any) -> bool:
    """The location's own "show description on label" setting; on by default."""
    return bool((storage.settings or {}).get('label_show_description', True))


def storage_label_caption(storage: Any, show_description: bool) -> str | None:
    """Text printed under the QR code on a storage label.

    The toggle offering this is called "show description on label", so the
    description is what it prints. Records written before the edit sheet
    offered a description field have none — those fall back to the name,
    which is what the label used to print unconditionally.
    """
    if not show_description:
        return None
    return storage.description or storage.name
