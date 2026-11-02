from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import partner_service
from app.services.partner_service import list_partners_async


@pytest.mark.asyncio
async def test_unknown_sort_is_refused_before_database_access() -> None:
    db = AsyncMock()
    with pytest.raises(ValueError):
        await list_partners_async(db, uuid4(), sort_by='hashed_password__whatever')
    db.execute.assert_not_awaited()
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['name', 'created_at', 'type'])
@pytest.mark.parametrize('order', ['asc', 'desc'])
async def test_supported_sort_fields_order_the_query(field, order, monkeypatch) -> None:
    paginate = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(partner_service, 'paginate_async', paginate)
    await list_partners_async(AsyncMock(), uuid4(), sort_by=field, sort_order=order)
    query = paginate.await_args.args[1]
    assert f'ORDER BY partners.{field}' in str(query)
    assert (' DESC' in str(query)) == (order == 'desc')
