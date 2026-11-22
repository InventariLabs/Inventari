"""A refusal puts a word in its sentence, never the row's own code.

Passes this comes from (the 2026-11 QA round): "Cannot change status from
MAINTENANCE to MAINTENANCE" in four languages (the equipment status machine
and the attestation campaigns handed the raw status to a translated
sentence), "Type: SUPPLIER" in the organization journal and "Usage: internal"
in an item's history. ``check_raw_stored_values_in_refusals.py`` holds the
class at the sites its baseline records; this file measures the gate itself
with a planted violation outside the baseline.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / 'scripts'
    / 'check_raw_stored_values_in_refusals.py'
)


@pytest.fixture(scope='module')
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location('raw_stored_values_gate', _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _found(gate: ModuleType, source: str) -> set[str]:
    return gate.findings_in('app/planted.py', ast.parse(source))


def test_a_raw_status_handed_to_a_keyed_refusal_is_found(gate: ModuleType) -> None:
    found = _found(
        gate,
        "raise ServiceRejectionError('cannot_change', old=row.status, new=new_status)",
    )

    assert found == {
        'app/planted.py::ServiceRejectionError(old=row.status)',
        'app/planted.py::ServiceRejectionError(new=new_status)',
    }


def test_an_enum_value_interpolated_into_an_f_string_is_found(gate: ModuleType) -> None:
    found = _found(gate, "raise ValueError(f'Type: {partner.type.value}')")

    assert found == {'app/planted.py::ValueError(f"{partner.type.value}")'}


def test_a_value_put_in_words_first_passes(gate: ModuleType) -> None:
    assert not _found(
        gate,
        "raise ServiceRejectionError('k', status=status_label(row.status, lang))",
    )


def test_a_name_that_is_not_a_stored_code_passes(gate: ModuleType) -> None:
    assert not _found(gate, "raise ServiceRejectionError('k', name=row.name, qty=qty)")


def test_the_tree_holds_no_site_beyond_the_baseline(gate: ModuleType) -> None:
    assert gate.scan() - gate.baseline() == set()
    assert gate.baseline() - gate.scan() == set(), 'fixed — refresh the baseline'
