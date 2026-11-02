"""The answer of a put-away: the posted move and what to ask about its shelf."""

from __future__ import annotations

from .putaway_schemas import HomeShelfOffer
from .schemas import DocumentSchema


class PutawayDone(DocumentSchema):
    """The posted move, and what the put-away has to say about the shelf.

    ``home_shelf`` is the offer to make the shelf the product's home (or why
    it cannot be one); it is empty when nothing is to be asked.
    """

    home_shelf: HomeShelfOffer | None = None
