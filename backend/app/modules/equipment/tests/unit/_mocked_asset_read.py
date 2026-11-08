"""The register's asset read, answered by a unit test's core_api mock."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import Any
from unittest.mock import patch
from uuid import UUID


@contextmanager
def asset_read_through(service: ModuleType, core: Callable[[], Any]) -> Iterator[None]:
    """Answer *service*'s ``get_asset_async`` from the core_api mock *core* returns.

    Whether a record is one of the register's assets is a database question,
    which the integration suite asks
    (``test_a_record_route_serves_only_the_registers_records``). These tests
    mock core_api instead, so the record the mock serves stands for an asset
    and the mock's ``None`` for an id the register does not know.
    """

    async def read(
        db: Any, org_id: UUID, item_id: UUID, *, include_archived: bool = False
    ) -> Any:
        items = core().items
        reader = items.get_any_async if include_archived else items.get_async
        return await reader(db, org_id, item_id)

    with patch.object(service, 'get_asset_async', read):
        yield
