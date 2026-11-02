"""Unit tests for product_template_metadata helpers."""

from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ContractViolationError
from app.core.product_template_metadata import (
    ALLOWED_META_NAMESPACES,
    get_template_namespace,
    get_template_nutrition,
    set_template_namespace,
    set_template_nutrition,
)


def _make_template(meta_data: dict | None = None) -> MagicMock:
    """Return a minimal mock that mimics ProductTemplate.meta_data."""
    tpl = MagicMock()
    tpl.meta_data = meta_data
    return tpl


class TestGetTemplateNamespace:
    def test_returns_none_when_meta_data_is_none(self):
        tpl = _make_template(None)
        assert get_template_namespace(tpl, 'nutrition') is None

    def test_returns_none_when_key_absent(self):
        tpl = _make_template({'specs': {'brand': 'Dell'}})
        assert get_template_namespace(tpl, 'nutrition') is None

    def test_returns_payload_when_key_present(self):
        payload = {'calories_kcal': 250}
        tpl = _make_template({'nutrition': payload})
        assert get_template_namespace(tpl, 'nutrition') == payload

    def test_does_not_validate_key_on_reads(self):
        """Reads with unknown keys should not raise."""
        tpl = _make_template({'unknown_key': {'foo': 'bar'}})
        assert get_template_namespace(tpl, 'unknown_key') == {'foo': 'bar'}


class TestSetTemplateNamespace:
    def test_writes_value_under_registered_key(self):
        tpl = _make_template(None)
        set_template_namespace(tpl, 'nutrition', {'calories_kcal': 100})
        assert tpl.meta_data == {'nutrition': {'calories_kcal': 100}}

    def test_does_not_overwrite_other_namespaces(self):
        tpl = _make_template({'specs': {'brand': 'Dell'}})
        set_template_namespace(tpl, 'nutrition', {'calories_kcal': 200})
        assert tpl.meta_data['specs'] == {'brand': 'Dell'}
        assert tpl.meta_data['nutrition'] == {'calories_kcal': 200}

    def test_removes_key_when_value_is_none(self):
        tpl = _make_template({'nutrition': {'calories_kcal': 300}, 'specs': {}})
        set_template_namespace(tpl, 'nutrition', None)
        assert 'nutrition' not in tpl.meta_data
        assert 'specs' in tpl.meta_data

    def test_sets_meta_data_to_none_when_last_key_removed(self):
        tpl = _make_template({'nutrition': {'calories_kcal': 50}})
        set_template_namespace(tpl, 'nutrition', None)
        assert tpl.meta_data is None

    def test_raises_for_unknown_namespace(self):
        tpl = _make_template(None)
        with pytest.raises(ContractViolationError, match='Unknown meta_data namespace'):
            set_template_namespace(tpl, 'unknown_namespace', {'foo': 'bar'})

    def test_raises_does_not_mutate_template_on_invalid_key(self):
        tpl = _make_template(None)
        with pytest.raises(ContractViolationError):
            set_template_namespace(tpl, 'bad_key', {'foo': 'bar'})
        assert tpl.meta_data is None

    def test_overwrites_existing_namespace_value(self):
        tpl = _make_template({'nutrition': {'calories_kcal': 100}})
        set_template_namespace(tpl, 'nutrition', {'calories_kcal': 999})
        assert tpl.meta_data == {'nutrition': {'calories_kcal': 999}}

    def test_all_allowed_namespaces_are_accepted(self):
        """Smoke test: every registered namespace must pass validation."""
        tpl = _make_template(None)
        for ns in ALLOWED_META_NAMESPACES:
            # Should not raise
            set_template_namespace(tpl, ns, {'value': 1})


class TestNutritionConvenienceHelpers:
    def test_get_template_nutrition_returns_nutrition_payload(self):
        expected = {'calories_kcal': 150, 'protein_g': 5}
        tpl = _make_template({'nutrition': expected})
        assert get_template_nutrition(tpl) == expected

    def test_get_template_nutrition_returns_none_when_absent(self):
        tpl = _make_template({'specs': {}})
        assert get_template_nutrition(tpl) is None

    def test_set_template_nutrition_writes_under_nutrition_key(self):
        tpl = _make_template(None)
        set_template_nutrition(tpl, {'calories_kcal': 200})
        assert tpl.meta_data == {'nutrition': {'calories_kcal': 200}}

    def test_set_template_nutrition_none_removes_nutrition(self):
        tpl = _make_template({'nutrition': {'calories_kcal': 200}, 'specs': {}})
        set_template_nutrition(tpl, None)
        assert 'nutrition' not in tpl.meta_data
        assert 'specs' in tpl.meta_data
