"""
Unit tests for CoreSettingsAPI secret handling — masking and decrypting.

Schema declares ``format: secret`` for sensitive leaves. ``get_async``
masks them (``'***'``); ``get_decrypted_async`` returns the real value.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import ContractViolationError
from app.core.module_registry import module_registry
from app.core.public_api.settings import CoreSettingsAPI


def _install_stub_module(name: str, schema):
    class _Stub:
        @property
        def metadata(self):
            from unittest.mock import MagicMock

            m = MagicMock()
            m.name = name
            return m

        def get_settings_schema(self):
            return schema

    stub = _Stub()
    module_registry.get = lambda n, _stub=stub: _stub if n == name else None  # type: ignore[method-assign]


def _make_async_db(org):
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=org)
    return db


def _make_org(settings):
    from unittest.mock import MagicMock

    org = MagicMock()
    org.settings = settings
    return org


@pytest.fixture(autouse=True)
def _restore_registry():
    yield
    module_registry.get = lambda name: module_registry._modules.get(name)  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_get_async_masks_secret_fields_by_default() -> None:
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
                },
                'count': {'type': 'integer'},
            },
        },
    )
    org = _make_org(
        {
            'module:demo': {
                'jina': {'api_key': 'enc:real-secret'},
                'count': 42,
            }
        }
    )
    api = CoreSettingsAPI()
    result = await api.get_async(_make_async_db(org), uuid4(), 'demo')
    from app.services.crypto_service import MASKED_VALUE

    assert result['jina']['api_key'] == MASKED_VALUE
    assert result['count'] == 42


@pytest.mark.asyncio
async def test_get_decrypted_async_returns_plaintext_secret() -> None:
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
                },
            },
        },
    )
    from app.services.crypto_service import encrypt_value

    plaintext = 'plain-secret-value'
    encrypted = encrypt_value(plaintext)
    org = _make_org({'module:demo': {'jina': {'api_key': encrypted}}})
    api = CoreSettingsAPI()

    value = await api.get_decrypted_async(
        _make_async_db(org), uuid4(), 'demo', 'jina.api_key'
    )
    assert value == plaintext


@pytest.mark.asyncio
async def test_get_async_returns_non_secret_unchanged() -> None:
    _install_stub_module(
        'demo',
        {
            'type': 'object',
            'properties': {
                'threshold': {'type': 'integer'},
            },
        },
    )
    org = _make_org({'module:demo': {'threshold': 15}})
    api = CoreSettingsAPI()
    result = await api.get_async(_make_async_db(org), uuid4(), 'demo')
    assert result == {'threshold': 15}


@pytest.mark.asyncio
async def test_get_async_handles_missing_module_gracefully() -> None:
    module_registry.get = lambda n: None  # type: ignore[method-assign]
    org = _make_org({'module:demo': {'secret': 'enc:real'}})
    api = CoreSettingsAPI()
    result = await api.get_async(_make_async_db(org), uuid4(), 'demo')
    assert result == {'secret': 'enc:real'}


@pytest.mark.asyncio
async def test_get_decrypted_async_refuses_a_whole_namespace() -> None:
    """No key means no answer, rather than an answer that is not plaintext.

    The keyless branch used to hand back the settings object exactly as
    stored — ciphertext for every secret field in it — under a name that
    promises the plaintext value, with nothing in the result to tell the two
    apart. Decrypting a namespace wholesale is also what the method's own
    warning says not to do, so it refuses instead.
    """
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
                },
            },
        },
    )
    org = _make_org({'module:demo': {'jina': {'api_key': 'enc:real-secret'}}})
    api = CoreSettingsAPI()

    with pytest.raises(ContractViolationError, match='needs a key'):
        await api.get_decrypted_async(_make_async_db(org), uuid4(), 'demo')


@pytest.mark.asyncio
async def test_get_async_is_the_way_to_read_the_whole_namespace() -> None:
    """The refusal above has somewhere to point: the masked object."""
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
                },
                'timeout': {'type': 'integer'},
            },
        },
    )
    org = _make_org(
        {'module:demo': {'jina': {'api_key': 'enc:real-secret'}, 'timeout': 30}}
    )
    api = CoreSettingsAPI()

    from app.services.crypto_service import MASKED_VALUE

    result = await api.get_async(_make_async_db(org), uuid4(), 'demo')
    assert result['jina']['api_key'] == MASKED_VALUE
    assert result['timeout'] == 30
