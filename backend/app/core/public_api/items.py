from __future__ import annotations

from app.core.public_api._items_reads import CoreItemsReadMixin
from app.core.public_api._items_stock_ops import CoreItemsStockOpsMixin
from app.core.public_api._items_writes import CoreItemsWritesMixin


class CoreItemsAPI(
    CoreItemsReadMixin,
    CoreItemsWritesMixin,
    CoreItemsStockOpsMixin,
):
    """Public Core API for modules that need read and write access to items.

    All data access is delegated to the item service layer — no direct DB model imports.
    Write methods run interceptors and emit events through the service pipeline.
    All methods are async-only (per repo Sync/Async Rule).
    """
