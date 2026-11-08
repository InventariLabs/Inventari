"""The settings-diff helper that feeds a journal entry.

A module-owned configuration write carries the same three things the
shared module-settings path journals: the actor, the source's name, and a
before/after limited to the keys that moved. Building that pair is
mechanical and lives in the core so a module's own route can call it
without reaching into another module or a service it may not import.
"""

from app.core.settings_diff import (
    MASKED_VALUE,
    ROTATED_VALUE,
    changed_settings_snapshot,
    record_settings,
)


def test_only_the_keys_that_moved_are_named() -> None:
    snapshot = changed_settings_snapshot(
        {'threshold': '100.00', 'required': False},
        {'threshold': '100.00', 'required': True},
    )

    assert snapshot == {
        'before': {'required': False},
        'after': {'required': True},
    }


def test_no_moved_key_answers_none() -> None:
    assert changed_settings_snapshot({'required': False}, {'required': False}) is None


def test_a_mapping_reads_as_json_safe_settings() -> None:
    from uuid import UUID

    settings = record_settings(
        {
            'id': UUID('11111111-1111-1111-1111-111111111111'),
            'padding': 6,
            'threshold': None,
            'note': 'kept',
        }
    )

    assert settings == {
        'id': '11111111-1111-1111-1111-111111111111',
        'padding': 6,
        'threshold': None,
        'note': 'kept',
    }


def test_a_number_compares_as_a_number_and_is_written_as_its_digits() -> None:
    from decimal import Decimal

    # The column holds 8.00 and the form posts 8: one rate, read twice.
    assert (
        changed_settings_snapshot(
            record_settings({'rate': Decimal('8.00')}),
            record_settings({'rate': Decimal('8')}),
        )
        is None
    )
    assert changed_settings_snapshot(
        record_settings({'rate': Decimal('8.00')}),
        record_settings({'rate': Decimal('9.5')}),
    ) == {'before': {'rate': '8.00'}, 'after': {'rate': '9.5'}}


def test_a_float_compares_as_a_number_like_a_decimal_does() -> None:
    from decimal import Decimal

    # A JSON setting seeded as 3.0 and posted as 3, or a Float column that
    # holds 8.0 beside the Decimal a form posts: one number, read twice.
    assert (
        changed_settings_snapshot(
            record_settings({'x': 3.0}), record_settings({'x': 3})
        )
        is None
    )
    assert (
        changed_settings_snapshot(
            record_settings({'x': Decimal('8.00')}), record_settings({'x': 8.0})
        )
        is None
    )
    # The same answer one level down.
    assert (
        changed_settings_snapshot(
            record_settings({'x': {'limits': [3.0, {'y': 1.50}]}}),
            record_settings({'x': {'limits': [3, {'y': Decimal('1.5')}]}}),
        )
        is None
    )
    assert changed_settings_snapshot(
        record_settings({'x': {'limit': 3.0}}),
        record_settings({'x': {'limit': 4.5}}),
    ) == {'before': {'x': {'limit': '3.0'}}, 'after': {'x': {'limit': '4.5'}}}


def test_an_extreme_float_is_written_in_plain_digits() -> None:
    from app.services.audit_service import audit_value

    assert audit_value(0.0000001) == '0.0000001'
    assert audit_value(1e16) == '10000000000000000'
    assert audit_value({'min': 1e-7}) == {'min': '0.0000001'}


def test_a_structured_value_compares_regardless_of_key_order() -> None:
    before = record_settings(
        {'scope': {'everyone': True, 'role_ids': [], 'user_ids': []}}
    )
    after = record_settings(
        {'scope': {'everyone': True, 'user_ids': [], 'role_ids': []}}
    )

    assert changed_settings_snapshot(before, after) is None
    assert changed_settings_snapshot(
        before, record_settings({'scope': {'everyone': False}})
    ) == {
        'before': {'scope': {'everyone': True, 'role_ids': [], 'user_ids': []}},
        'after': {'scope': {'everyone': False}},
    }


def test_a_rotated_secret_still_reads_as_a_change() -> None:
    """Ten asterisks on both sides of the arrow said nothing happened.

    The reading side drops a line whose two halves are equal, so a key
    that had just been replaced came out as a dash in the Details column.
    The value stays hidden; the fact that it moved does not.
    """
    snapshot = changed_settings_snapshot(
        {'jina': {'api_key': 'enc:old'}},
        {'jina': {'api_key': 'enc:new'}},
        secret_paths={('jina', 'api_key')},
    )

    assert snapshot is not None
    assert snapshot['before']['jina']['api_key'] == MASKED_VALUE
    assert snapshot['after']['jina']['api_key'] == ROTATED_VALUE
    assert snapshot['before']['jina']['api_key'] != snapshot['after']['jina']['api_key']
    assert 'enc:' not in str(snapshot)


def test_a_secret_set_for_the_first_time_is_not_called_a_rotation() -> None:
    snapshot = changed_settings_snapshot(
        {'jina': {'api_key': ''}},
        {'jina': {'api_key': 'enc:new'}},
        secret_paths={('jina', 'api_key')},
    )

    assert snapshot is not None
    assert snapshot['before']['jina']['api_key'] == ''
    assert snapshot['after']['jina']['api_key'] == MASKED_VALUE


def test_a_stored_ciphertext_is_hidden_even_where_no_schema_names_it() -> None:
    """The declaration is the contract; the prefix is the backstop.

    A module-owned configuration row can carry a secret column no settings
    schema describes — the gate over the declared path stays green while
    the value sits in the journal in the clear.
    """
    snapshot = changed_settings_snapshot(
        {'printer_token': 'enc:mod1:OLD=='},
        {'printer_token': 'enc:mod1:NEW=='},
    )

    assert snapshot is not None
    assert snapshot['before']['printer_token'] == MASKED_VALUE
    assert snapshot['after']['printer_token'] == ROTATED_VALUE
    assert 'enc:' not in str(snapshot)


async def test_a_module_owned_route_masks_what_the_modules_schema_declares(
    monkeypatch,
) -> None:
    """AC: the same source, not a second list.

    A module's own configuration route never says which of its columns hold
    a secret. The shared settings path asks the module's schema; this one
    asks the same schema, so a module that declares a leaf secret gets it
    masked on every route it owns without telling any of them.
    """
    from unittest.mock import MagicMock

    from app.core.module_registry import module_registry
    from app.core.public_api import core_api
    from app.core.settings_diff import journal_config_change

    class _Stub:
        def get_settings_schema(self):
            return {
                'type': 'object',
                'properties': {
                    'printer_token': {'type': 'string', 'format': 'secret'},
                },
            }

    monkeypatch.setattr(
        module_registry, 'get', lambda name: _Stub() if name == 'labels' else None
    )

    written: dict = {}

    async def _capture(_db, **kwargs):
        written.update(kwargs)

    monkeypatch.setattr(core_api.audit_log, 'log_action_async', _capture)

    await journal_config_change(
        MagicMock(),
        'org',
        'user',
        module='labels',
        subject='settings',
        keys={'printer_token'},
        # Plaintext on purpose: the declaration is what has to carry this,
        # not the ciphertext backstop standing behind it.
        before={'printer_token': 'old-plaintext-token'},
        after={'printer_token': 'new-plaintext-token'},
    )

    snapshot = written['snapshot']
    assert 'plaintext' not in str(snapshot)
    assert snapshot['before']['printer_token'] == MASKED_VALUE
    assert snapshot['after']['printer_token'] == ROTATED_VALUE
