"""Unit tests for ``app.core.llm.structured_extraction``.

Reading a declared shape out of a model\'s answer, exercised through a schema
that stands in for any caller\'s. Two responsibilities covered separately:
getting JSON out of whatever the model wrote, and unwrapping the envelope it
put the object in. These lived in the vision module and were vision\'s alone
until the capability moved to Core, where three verticals share it.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from app.core.llm.errors import LlmContractError
from app.core.llm.structured_extraction import parse_into


class Reading(BaseModel):
    """A stand-in caller schema.

    Deliberately not any real module\'s: Core owns this code and must be
    testable without one, and the properties under test — optional fields, a
    numeric field a weak model will answer in prose — are what every caller\'s
    extraction schema has in common.
    """

    name: str | None = None
    weight: str | None = None
    brand: str | None = None
    notes: str | None = None
    weight_value: float | None = None
    count: int | None = None


def parse_vision_content(content: str) -> Reading:
    """The capability under test, bound to one caller\'s schema."""
    return parse_into(Reading, content)


@pytest.mark.unit
class TestDirtyModelOutput:
    """Shapes that raised ``json.JSONDecodeError`` before Core's parser."""

    def test_fence_after_a_preamble(self) -> None:
        raw = 'Sure! Here is the JSON:\n```json\n{"name": "Milk 2%"}\n```'
        assert parse_vision_content(raw).name == 'Milk 2%'

    def test_raw_newline_inside_a_string_value(self) -> None:
        raw = '{"name": "Milk", "notes": "water\nmilk powder"}'
        result = parse_vision_content(raw)
        assert result.name == 'Milk'
        assert result.notes == 'water\nmilk powder'

    def test_response_cut_off_by_the_token_budget(self) -> None:
        raw = '{"name": "Milk 2%", "weight": "1 l", "brand": "Mlek'
        result = parse_vision_content(raw)
        assert result.name == 'Milk 2%'
        assert result.weight == '1 l'

    def test_trailing_commentary_after_the_object(self) -> None:
        raw = '{"name": "Milk"}\n\nLet me know if you need anything else.'
        assert parse_vision_content(raw).name == 'Milk'


@pytest.mark.unit
class TestUnwrap:
    def test_direct_object(self) -> None:
        result = parse_vision_content('{"name": "Milk"}')
        assert isinstance(result, Reading)
        assert result.name == 'Milk'

    def test_list_with_one_element(self) -> None:
        assert parse_vision_content('[{"name": "Milk"}]').name == 'Milk'

    def test_single_key_dict_wrapper(self) -> None:
        assert parse_vision_content('{"product": {"name": "Milk"}}').name == 'Milk'

    def test_single_key_dict_with_list_value(self) -> None:
        assert parse_vision_content('{"data": [{"name": "Milk"}]}').name == 'Milk'

    def test_empty_list_raises(self) -> None:
        with pytest.raises(LlmContractError, match='empty list'):
            parse_vision_content('[]')

    def test_empty_list_under_a_key_raises(self) -> None:
        with pytest.raises(LlmContractError, match='empty list under key'):
            parse_vision_content('{"products": []}')

    def test_scalar_payload_raises(self) -> None:
        with pytest.raises(LlmContractError, match='not a dict after unwrap'):
            parse_vision_content('[1, 2, 3]')


@pytest.mark.unit
class TestValueTypeMismatch:
    """The failure that actually happens: right key, unusable value.

    Every field on an extraction schema is optional, so a *missing* field
    cannot fail. A weaker model answering ``"about 500 g"`` where a number
    belongs can, and did — as a raw ``ValidationError`` all the way out.
    """

    def test_number_given_as_prose_raises_contract_error(self) -> None:
        raw = '{"name": "Milk", "weight_value": "about 500 g"}'
        with pytest.raises(LlmContractError) as exc:
            parse_vision_content(raw)
        assert 'weight_value' in str(exc.value)
        assert 'about 500 g' in str(exc.value)

    def test_every_offending_field_is_named(self) -> None:
        raw = '{"weight_value": "a lot", "count": "unknown"}'
        with pytest.raises(LlmContractError) as exc:
            parse_vision_content(raw)
        assert 'weight_value' in str(exc.value)
        assert 'count' in str(exc.value)

    def test_oversized_value_is_truncated_in_the_message(self) -> None:
        raw = json.dumps({'weight_value': 'x' * 500})
        with pytest.raises(LlmContractError) as exc:
            parse_vision_content(raw)
        assert len(str(exc.value)) < 400


@pytest.mark.unit
class TestProseInsteadOfJson:
    """Not-JSON is reported as a contract failure, like every other way the
    model can miss the deal — one ``except`` upstream, not two."""

    def test_model_refusal_raises_contract_error(self) -> None:
        with pytest.raises(LlmContractError, match='did not return JSON'):
            parse_vision_content('I am sorry, I cannot read this label.')

    def test_the_answer_is_quoted_so_the_log_shows_what_arrived(self) -> None:
        with pytest.raises(LlmContractError) as exc:
            parse_vision_content('I am sorry, I cannot read this label.')
        assert 'I am sorry' in str(exc.value)

    def test_a_rambling_refusal_does_not_become_the_message(self) -> None:
        with pytest.raises(LlmContractError) as exc:
            parse_vision_content('I am sorry. ' * 200)
        assert len(str(exc.value)) < 200


@pytest.mark.unit
class TestNestedFieldIsNotAnEnvelope:
    """A key the schema declares is never a wrapper the model invented.

    Once a schema gained a nested group, an answer that filled only that group
    was shaped exactly like an envelope — one key, an object under it. The
    unwrap took it apart and returned a model of nulls, losing the one thing
    the model had actually read.
    """

    class Nested(BaseModel):
        energy_kcal: float | None = None

    class Composed(BaseModel):
        name: str | None = None
        nutrition: TestNestedFieldIsNotAnEnvelope.Nested | None = None

    def test_an_answer_filling_only_a_nested_group_survives(self) -> None:
        result = parse_into(self.Composed, '{"nutrition": {"energy_kcal": 42}}')
        assert result.nutrition is not None
        assert result.nutrition.energy_kcal == 42.0

    def test_a_key_the_schema_does_not_know_is_still_unwrapped(self) -> None:
        result = parse_into(self.Composed, '{"product": {"name": "Milk"}}')
        assert result.name == 'Milk'
