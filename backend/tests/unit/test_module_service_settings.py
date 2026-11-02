"""
Unit tests for ModuleService.update_module_settings_async with schema validation.

The service now:
1. Looks up the module's ``get_settings_schema()``.
2. Validates the payload against it (raising ``SchemaValidationError``).
3. Applies schema-defined defaults for any missing keys.
4. Encrypts any ``format: secret`` fields via ``crypto_service.encrypt_value``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.module_registry import module_registry
from app.core.settings_validator import SchemaValidationError
from app.services import module_service


@pytest.fixture(autouse=True)
def _clean_registry():
    from app.services import _org_reads

    registry = module_registry
    original_get = registry.get
    original_org_get = _org_reads.get_by_id_async
    yield
    registry.get = original_get  # type: ignore[method-assign]
    _org_reads.get_by_id_async = original_org_get


def _install_stub_module(name: str, schema):
    class _Stub:
        @property
        def metadata(self):
            m = MagicMock()
            m.name = name
            return m

        def get_settings_schema(self):
            return schema

    stub = _Stub()
    module_registry.get = lambda n, _stub=stub: _stub if n == name else None  # type: ignore[method-assign]


async def test_validate_against_module_schema_passes_valid_payload() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {
                'count': {'type': 'integer', 'minimum': 1, 'maximum': 5},
                'name': {'type': 'string', 'minLength': 1},
            },
            'required': ['count'],
            'additionalProperties': False,
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = None
    db.execute = AsyncMock()

    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {'count': 3, 'name': 'x'}
    )

    assert 'module:demo' in org.settings
    assert org.settings['module:demo']['count'] == 3


async def test_validate_rejects_payload_below_minimum() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {'n': {'type': 'integer', 'minimum': 5}},
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    with pytest.raises(SchemaValidationError) as exc:
        await module_service.ModuleService.update_module_settings_async(
            db, uuid4(), 'demo', {'n': 1}
        )
    assert exc.value.key == 'settings_number_too_small'
    assert exc.value.kwargs['path'] == 'n'


async def test_validate_rejects_unknown_field_when_additional_properties_false() -> (
    None
):
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {'a': {'type': 'integer'}},
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    with pytest.raises(SchemaValidationError) as exc:
        await module_service.ModuleService.update_module_settings_async(
            db, uuid4(), 'demo', {'a': 1, 'b': 'rogue'}
        )
    assert exc.value.key == 'settings_field_unknown'
    assert exc.value.kwargs['field'] == 'b'


async def test_secret_field_is_encrypted_on_write() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {
                'jina': {
                    'type': 'object',
                    'properties': {
                        'api_key': {'type': 'string', 'format': 'secret'},
                    },
                    'required': ['api_key'],
                },
            },
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {'jina': {'api_key': 'plain-secret-value'}}
    )

    stored = org.settings['module:demo']['jina']['api_key']
    assert stored.startswith('enc:')
    assert 'plain-secret-value' not in stored


async def test_schema_defaults_applied_for_missing_optional_keys() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {
                'limit': {'type': 'integer', 'default': 10},
                'enabled': {'type': 'boolean', 'default': False},
            },
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {}
    )

    assert org.settings['module:demo']['limit'] == 10
    assert org.settings['module:demo']['enabled'] is False


async def test_module_without_schema_accepts_empty_payload() -> None:
    _install_stub_module('legacy', None)

    db = AsyncMock()
    org = MagicMock()
    org.settings = {}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'legacy', {'anything': 'goes'}
    )
    assert org.settings['module:legacy'] == {
        'anything': 'goes',
        '__schema_version': 1,
    }


async def test_the_returned_snapshot_names_the_keys_that_moved() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {
                'limit': {'type': 'integer', 'default': 10},
            },
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    result = await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {'limit': 25}
    )

    # The key is new to the organization, so the before side reads the
    # schema default — absence meant 10, and the journal says so.
    assert result == {'before': {'limit': 10}, 'after': {'limit': 25}}


async def test_a_setting_that_changes_nothing_gets_no_snapshot() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {
                'limit': {'type': 'integer'},
            },
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {'module:demo': {'limit': 10}}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    result = await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {'limit': 10}
    )

    assert result is None


async def test_a_secret_is_masked_in_the_snapshot() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {
                'jina': {
                    'type': 'object',
                    'properties': {
                        'api_key': {'type': 'string', 'format': 'secret'},
                    },
                    'required': ['api_key'],
                },
            },
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    result = await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {'jina': {'api_key': 'plain-new-secret'}}
    )

    assert result is not None
    import json

    dump = json.dumps(result)
    assert 'plain-new-secret' not in dump
    assert 'enc:' not in dump
    from app.services.crypto_service import MASKED_VALUE

    assert result['after']['jina']['api_key'] == MASKED_VALUE


async def test_sending_the_mask_back_keeps_the_stored_secret() -> None:
    """GET hands the mask out for "unchanged"; the settings round-trip sends
    it back. Encrypting that literal overwrote the real key with ten
    asterisks — the stored value must survive, and a field the reader did
    not change journals nothing."""
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {
                'jina': {
                    'type': 'object',
                    'properties': {
                        'api_key': {'type': 'string', 'format': 'secret'},
                    },
                    'required': ['api_key'],
                },
            },
        },
    )

    db = AsyncMock()
    org = MagicMock()
    stored = 'enc:the-real-secret'
    org.settings = {'module:demo': {'jina': {'api_key': stored}}}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    from app.services.crypto_service import MASKED_VALUE

    result = await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {'jina': {'api_key': MASKED_VALUE}}
    )

    assert org.settings['module:demo']['jina']['api_key'] == stored
    assert result is None


async def test_the_write_stamps_the_declared_schema_version() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'version': 2,
            'properties': {'limit': {'type': 'integer'}},
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {'limit': 5}
    )

    assert org.settings['module:demo'] == {'limit': 5, '__schema_version': 2}


async def test_the_write_stamps_version_one_without_a_schema() -> None:
    _install_stub_module('legacy', None)

    db = AsyncMock()
    org = MagicMock()
    org.settings = {}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'legacy', {'anything': 'goes'}
    )

    assert org.settings['module:legacy']['__schema_version'] == 1


async def test_the_snapshot_never_shows_the_schema_version_stamp() -> None:
    """The stamp is core's metadata: a journal entry names the keys the
    reader moved, not the version the write re-stamped beside them."""
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'version': 2,
            'properties': {'limit': {'type': 'integer'}},
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {'module:demo': {'limit': 5, '__schema_version': 1}}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    result = await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {'limit': 6}
    )

    assert result == {'before': {'limit': 5}, 'after': {'limit': 6}}


async def test_a_write_that_only_moves_the_stamp_journals_nothing() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'version': 2,
            'properties': {'limit': {'type': 'integer'}},
        },
    )

    db = AsyncMock()
    org = MagicMock()
    org.settings = {'module:demo': {'limit': 5, '__schema_version': 1}}
    from app.services import _org_reads

    _org_reads.get_by_id_async = AsyncMock(return_value=org)

    result = await module_service.ModuleService.update_module_settings_async(
        db, uuid4(), 'demo', {'limit': 5}
    )

    assert result is None
    assert org.settings['module:demo'] == {'limit': 5, '__schema_version': 2}
