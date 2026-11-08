"""
Unit tests for the InterceptorPipeline.

Tests cover:
- Priority-based execution order
- Sequential data modification (each interceptor receives output of previous)
- InterceptorError blocking the pipeline
- Empty pipeline pass-through
- After-create / after-update hooks
- StorageInterceptor registration and execution
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.interceptors import (
    InterceptorError,
    InterceptorPipeline,
    ItemInterceptor,
    StorageInterceptor,
)


def _make_context():
    return MagicMock(name='ModuleContext')


# ---------------------------------------------------------------------------
# Concrete interceptor helpers
# ---------------------------------------------------------------------------


class TaggingItemInterceptor(ItemInterceptor):
    """Appends its own tag to data['tags'] list."""

    def __init__(self, tag: str, priority: int = 100) -> None:
        self.tag = tag
        self.priority = priority

    async def before_create(self, data: dict, context) -> dict:
        data.setdefault('tags', []).append(self.tag)
        return data

    async def before_update(self, item_id, changes: dict, context) -> dict:
        changes.setdefault('tags', []).append(self.tag)
        return changes


class BlockingItemInterceptor(ItemInterceptor):
    """Always blocks with InterceptorError."""

    priority = 50

    async def before_create(self, data: dict, context) -> dict:
        raise InterceptorError('blocked by test', error_code='TEST_BLOCK')

    async def before_update(self, item_id, changes: dict, context) -> dict:
        raise InterceptorError('update blocked by test', error_code='TEST_BLOCK')


class AfterHookItemInterceptor(ItemInterceptor):
    """Records calls to after_create / after_update."""

    def __init__(self) -> None:
        self.after_create_called = False
        self.after_update_called = False

    async def before_create(self, data: dict, context) -> dict:
        return data

    async def before_update(self, item_id, changes: dict, context) -> dict:
        return changes

    async def after_create(self, item_id, data: dict, context) -> None:
        self.after_create_called = True

    async def after_update(self, item_id, changes: dict, context) -> None:
        self.after_update_called = True


class TaggingStorageInterceptor(StorageInterceptor):
    """Appends tag to data['tags']."""

    def __init__(self, tag: str, priority: int = 100) -> None:
        self.tag = tag
        self.priority = priority

    async def before_create(self, data: dict, context) -> dict:
        data.setdefault('tags', []).append(self.tag)
        return data

    async def before_update(self, storage_id, changes: dict, context) -> dict:
        changes.setdefault('tags', []).append(self.tag)
        return changes


# ---------------------------------------------------------------------------
# Empty pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_pipeline_passthrough_create():
    pipeline = InterceptorPipeline()
    ctx = _make_context()
    data = {'name': 'test item'}
    result = await pipeline.run_before_item_create(data, ctx)
    assert result == {'name': 'test item'}


@pytest.mark.asyncio
async def test_empty_pipeline_passthrough_update():
    pipeline = InterceptorPipeline()
    ctx = _make_context()
    changes = {'quantity': 5}
    result = await pipeline.run_before_item_update(uuid4(), changes, ctx)
    assert result == {'quantity': 5}


# ---------------------------------------------------------------------------
# Sequential data modification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sequential_modification_before_create():
    pipeline = InterceptorPipeline()
    pipeline.register_item_interceptor(TaggingItemInterceptor('first'))
    pipeline.register_item_interceptor(TaggingItemInterceptor('second'))

    ctx = _make_context()
    result = await pipeline.run_before_item_create({}, ctx)
    assert result['tags'] == ['first', 'second']


@pytest.mark.asyncio
async def test_sequential_modification_before_update():
    pipeline = InterceptorPipeline()
    pipeline.register_item_interceptor(TaggingItemInterceptor('alpha'))
    pipeline.register_item_interceptor(TaggingItemInterceptor('beta'))

    result = await pipeline.run_before_item_update(uuid4(), {}, _make_context())
    assert result['tags'] == ['alpha', 'beta']


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_priority_ordering_before_create():
    pipeline = InterceptorPipeline()
    # Register in reverse priority order deliberately
    pipeline.register_item_interceptor(TaggingItemInterceptor('high', priority=10))
    pipeline.register_item_interceptor(TaggingItemInterceptor('low', priority=200))
    pipeline.register_item_interceptor(TaggingItemInterceptor('mid', priority=50))

    result = await pipeline.run_before_item_create({}, _make_context())
    assert result['tags'] == ['high', 'mid', 'low']


# ---------------------------------------------------------------------------
# InterceptorError blocks pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interceptor_error_blocks_create():
    pipeline = InterceptorPipeline()
    pipeline.register_item_interceptor(BlockingItemInterceptor())
    pipeline.register_item_interceptor(
        TaggingItemInterceptor('should_not_run', priority=200)
    )

    with pytest.raises(InterceptorError) as exc_info:
        await pipeline.run_before_item_create({}, _make_context())

    assert exc_info.value.error_code == 'TEST_BLOCK'
    assert 'blocked' in exc_info.value.message


@pytest.mark.asyncio
async def test_interceptor_error_blocks_update():
    pipeline = InterceptorPipeline()
    pipeline.register_item_interceptor(BlockingItemInterceptor())

    with pytest.raises(InterceptorError):
        await pipeline.run_before_item_update(uuid4(), {}, _make_context())


# ---------------------------------------------------------------------------
# After hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_after_create_hook_called():
    pipeline = InterceptorPipeline()
    hook = AfterHookItemInterceptor()
    pipeline.register_item_interceptor(hook)

    await pipeline.run_after_item_create(uuid4(), {}, _make_context())
    assert hook.after_create_called is True


@pytest.mark.asyncio
async def test_after_update_hook_called():
    pipeline = InterceptorPipeline()
    hook = AfterHookItemInterceptor()
    pipeline.register_item_interceptor(hook)

    await pipeline.run_after_item_update(uuid4(), {}, _make_context())
    assert hook.after_update_called is True


@pytest.mark.asyncio
async def test_after_hooks_not_called_when_no_interceptors():
    pipeline = InterceptorPipeline()
    # Should not raise
    await pipeline.run_after_item_create(uuid4(), {}, _make_context())
    await pipeline.run_after_item_update(uuid4(), {}, _make_context())


# ---------------------------------------------------------------------------
# StorageInterceptor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_interceptor_before_create():
    pipeline = InterceptorPipeline()
    pipeline.register_storage_interceptor(TaggingStorageInterceptor('s1'))
    pipeline.register_storage_interceptor(TaggingStorageInterceptor('s2'))

    result = await pipeline.run_before_storage_create({}, _make_context())
    assert result['tags'] == ['s1', 's2']


@pytest.mark.asyncio
async def test_storage_interceptor_before_update():
    pipeline = InterceptorPipeline()
    pipeline.register_storage_interceptor(TaggingStorageInterceptor('su1'))

    result = await pipeline.run_before_storage_update(uuid4(), {}, _make_context())
    assert result['tags'] == ['su1']


@pytest.mark.asyncio
async def test_storage_interceptor_priority_ordering():
    pipeline = InterceptorPipeline()
    pipeline.register_storage_interceptor(
        TaggingStorageInterceptor('last', priority=200)
    )
    pipeline.register_storage_interceptor(
        TaggingStorageInterceptor('first', priority=10)
    )

    result = await pipeline.run_before_storage_create({}, _make_context())
    assert result['tags'] == ['first', 'last']


# ---------------------------------------------------------------------------
# InterceptorError attributes
# ---------------------------------------------------------------------------


def test_interceptor_error_defaults():
    err = InterceptorError('oops')
    assert err.message == 'oops'
    assert err.error_code == 'INTERCEPTOR_BLOCKED'
    assert str(err) == 'oops'


def test_interceptor_error_custom_code():
    err = InterceptorError('custom error', error_code='MY_CODE')
    assert err.error_code == 'MY_CODE'


# ---------------------------------------------------------------------------
# Idempotent registration (no duplicates)
# ---------------------------------------------------------------------------


def test_register_item_interceptor_dedup():
    """Re-registering the same interceptor instance must not duplicate it."""
    pipeline = InterceptorPipeline()
    interceptor = TaggingItemInterceptor('solo')

    pipeline.register_item_interceptor(interceptor)
    pipeline.register_item_interceptor(interceptor)
    pipeline.register_item_interceptor(interceptor)

    assert len(pipeline._item_interceptors) == 1


def test_register_storage_interceptor_dedup():
    """Re-registering the same storage interceptor must not duplicate it."""
    pipeline = InterceptorPipeline()
    interceptor = TaggingStorageInterceptor('solo')

    pipeline.register_storage_interceptor(interceptor)
    pipeline.register_storage_interceptor(interceptor)

    assert len(pipeline._storage_interceptors) == 1


def test_register_category_interceptor_dedup():
    """Re-registering the same category interceptor must not duplicate it."""
    from app.core.interceptors import CategoryInterceptor

    class DummyCategoryInterceptor(CategoryInterceptor):
        priority = 100

        async def before_create(self, data, context):
            return data

        async def before_update(self, entity_id, changes, context):
            return changes

    pipeline = InterceptorPipeline()
    interceptor = DummyCategoryInterceptor()

    pipeline.register_category_interceptor(interceptor)
    pipeline.register_category_interceptor(interceptor)

    assert len(pipeline._category_interceptors) == 1


# ---------------------------------------------------------------------------
# The three bases agree on what a subclass must write
# ---------------------------------------------------------------------------


class _AfterCreateOnly(ItemInterceptor):
    """An item interceptor that only needs to hear about a new item."""

    def __init__(self) -> None:
        self.created: list[object] = []

    async def after_create(self, item_id, data: dict, context) -> None:
        self.created.append(item_id)


@pytest.mark.asyncio
async def test_an_item_interceptor_may_override_only_an_after_hook():
    """Storage and category interceptors never had to stub the before hooks;
    an item interceptor did, or it failed when it was instantiated."""
    interceptor = _AfterCreateOnly()
    pipeline = InterceptorPipeline()
    pipeline.register_item_interceptor(interceptor)
    ctx = _make_context()
    item_id = uuid4()

    assert await pipeline.run_before_item_create({'name': 'x'}, ctx) == {'name': 'x'}
    assert await pipeline.run_before_item_update(item_id, {'q': 1}, ctx) == {'q': 1}
    await pipeline.run_after_item_create(item_id, {}, ctx)
    assert interceptor.created == [item_id]
