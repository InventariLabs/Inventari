"""Unit tests for the shared, resilient LLM JSON parser.

Every case here is a shape a real model has produced at some point: fenced
output, a chatty preamble, a raw newline inside a string, a response cut off
by the token budget. The parser's job is to get the payload out anyway; when
it genuinely cannot, it must fail as ``json.JSONDecodeError`` so call sites
can tell "the model wrote prose" apart from "the network died".
"""

import json

import pytest

from app.core.llm.json_parsing import (
    extract_json,
    extract_json_object,
    repair_json_strings,
    strip_markdown_fence,
)


class TestStripMarkdownFence:
    def test_json_tagged_fence(self):
        assert strip_markdown_fence('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_bare_fence(self):
        assert strip_markdown_fence('```\n[]\n```') == '[]'

    def test_unfenced_text_is_unchanged(self):
        assert strip_markdown_fence('[{"name": "flour"}]') == '[{"name": "flour"}]'

    def test_fence_in_the_middle_of_prose(self):
        raw = 'Here is the JSON:\n```json\n{"a": 1}\n```\nHope that helps!'
        assert strip_markdown_fence(raw) == '{"a": 1}'

    def test_unterminated_fence_loses_only_the_opener(self):
        assert strip_markdown_fence('```json\n{"a": 1') == '{"a": 1'


class TestRepairJsonStrings:
    def test_raw_newline_inside_string_is_escaped(self):
        repaired = repair_json_strings('{"title": "line1\nline2"}')
        assert json.loads(repaired)['title'] == 'line1\nline2'

    def test_raw_tab_and_carriage_return_inside_string(self):
        repaired = repair_json_strings('{"title": "a\tb\rc"}')
        assert json.loads(repaired)['title'] == 'a\tb\rc'

    def test_newline_outside_string_is_left_alone(self):
        raw = '{\n  "title": "X"\n}'
        assert repair_json_strings(raw) == raw

    def test_escaped_backslash_is_preserved(self):
        repaired = repair_json_strings('{"title": "a \\\\ b"}')
        assert json.loads(repaired)['title'] == 'a \\ b'

    def test_escaped_quote_does_not_end_the_string(self):
        repaired = repair_json_strings('{"title": "say \\"hi\\"\nnow"}')
        assert json.loads(repaired)['title'] == 'say "hi"\nnow'


class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"a": 1}') == {'a': 1}

    def test_plain_list(self):
        assert extract_json('[1, 2]') == [1, 2]

    def test_fenced_object(self):
        assert extract_json('```json\n{"a": 1}\n```') == {'a': 1}

    def test_preamble_before_the_payload(self):
        assert extract_json('Here is the JSON: {"a": 1}') == {'a': 1}

    def test_postamble_after_the_payload(self):
        assert extract_json('{"a": 1}\n\nLet me know if you need more.') == {'a': 1}

    def test_preamble_before_a_list(self):
        assert extract_json('Sure! [{"name": "flour"}] — enjoy.') == [{'name': 'flour'}]

    def test_raw_newlines_inside_strings(self):
        raw = '{"instructions": "step one\nstep two"}'
        assert extract_json(raw)['instructions'] == 'step one\nstep two'

    def test_fenced_with_preamble_and_raw_newlines(self):
        raw = 'Here you go:\n```json\n{"title": "a\nb"}\n```'
        assert extract_json(raw)['title'] == 'a\nb'

    def test_block_extracted_from_prose_is_also_repaired(self):
        raw = 'prefix {"title": "line1\nline2"} suffix'
        assert extract_json(raw)['title'] == 'line1\nline2'

    def test_braces_inside_strings_do_not_break_block_extraction(self):
        raw = 'Result: {"note": "use {braces} and [brackets] freely"} done'
        assert extract_json(raw) == {'note': 'use {braces} and [brackets] freely'}

    def test_first_of_two_blocks_wins(self):
        assert extract_json('{"a": 1} and then {"b": 2}') == {'a': 1}

    def test_second_block_is_used_when_the_first_is_not_json(self):
        assert extract_json('{not json} but {"b": 2}') == {'b': 2}

    def test_truncated_object_is_completed(self):
        assert extract_json('{"a": 1, "b": {"c": 2}') == {'a': 1, 'b': {'c': 2}}

    def test_truncated_inside_a_string_drops_the_partial_member(self):
        assert extract_json('{"a": 1, "b": "unfinis') == {'a': 1}

    def test_truncated_list_keeps_the_complete_elements(self):
        raw = '[{"name": "flour"}, {"name": "sug'
        assert extract_json(raw) == [{'name': 'flour'}]

    def test_truncated_after_a_key(self):
        assert extract_json('{"a": 1, "b":') == {'a': 1}

    def test_truncated_fenced_response(self):
        assert extract_json('```json\n{"a": 1, "b": 2') == {'a': 1, 'b': 2}

    @pytest.mark.parametrize(
        'raw',
        [
            '',
            '   ',
            'no braces here',
            'I am sorry, I cannot read this image.',
            'prefix {"title": invalid} suffix',
        ],
    )
    def test_unparseable_input_raises_json_decode_error(self, raw):
        with pytest.raises(json.JSONDecodeError):
            extract_json(raw)


class TestExtractJsonObject:
    def test_returns_dict(self):
        assert extract_json_object('{"a": 1}') == {'a': 1}

    def test_list_payload_raises_type_error(self):
        with pytest.raises(TypeError):
            extract_json_object('[1, 2]')

    def test_scalar_payload_raises_type_error(self):
        with pytest.raises(TypeError):
            extract_json_object('42')

    def test_unparseable_still_raises_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json_object('nothing here')


class TestNoModuleDependencies:
    """The parser is Core: it must not reach into feature modules."""

    def test_imports_stdlib_only(self):
        import pathlib

        from app.core.llm import json_parsing

        source = pathlib.Path(json_parsing.__file__).read_text(encoding='utf-8')
        for line in source.splitlines():
            if line.startswith(('import ', 'from ')):
                assert 'app.' not in line, f'module dependency leaked in: {line}'
