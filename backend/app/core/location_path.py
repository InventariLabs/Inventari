"""The one way a location's path is written: ``Main Warehouse › Zone A › Shelf 1``.

The screens, the exports, the sentences a refusal prints and the picking
sheets all name a place by the chain of names above it, and the chain is
joined with one character everywhere. It is not ``→``: that arrow says a
document's goods went *from* one place *to* another, and a path written with
it read as a journey. The frontend writes the same separator
(``LOCATION_PATH_SEPARATOR`` in ``utils/helpers``).
"""

from collections.abc import Iterable

LOCATION_PATH_SEPARATOR = ' › '


def join_location_path(names: Iterable[str]) -> str:
    """Names, outermost first, as a path."""
    return LOCATION_PATH_SEPARATOR.join(names)
