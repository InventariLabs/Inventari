"""Regenerating the rejection ledger twice leaves the same file.

The generator collected every leading comment as prose it must preserve —
and the counts block it had written itself is a comment. So each run kept
the old block and appended a new one: the committed ledger carried three,
the first holding numbers that contradicted the two below it. The gate and
the ratchet read entries, not comments, so nothing went red; the file simply
stopped telling the truth about itself.

These tests pin the property that was missing rather than the symptom: a
rewrite is idempotent, the prose survives it, and the command can say which
debt it took on and which it retired.
"""

import ast
from pathlib import Path

from app.core.architecture_lint._quality_checks_rejections import (
    COUNTS_BEGIN,
    counts_by_group,
    keyed_dynamic_value_error_entries,
    ledger_entries,
    raw_value_error_sentence_entries,
    refusal_class_names,
    rejection_group_for_entry,
    write_rejection_ledger,
)

PROSE = [
    '# Ledger of plain ``ValueError`` sentence literals still raised in app/.',
    '# A line here is debt, never permission.',
]


def _app_tree(tmp_path: Path, body: str, *, subdir: str = 'modules') -> Path:
    app_root = tmp_path / 'app'
    target = app_root / subdir
    target.mkdir(parents=True)
    (target / 'thing_service.py').write_text(body, encoding='utf-8')
    return app_root


class TestTheLedgerRewriteIsIdempotent:
    def test_a_second_run_changes_nothing(self, tmp_path: Path) -> None:
        app_root = _app_tree(
            tmp_path,
            "raise ValueError('no recipe for this product')\n",
            subdir='cli',
        )
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text('\n'.join(PROSE) + '\n', encoding='utf-8')

        write_rejection_ledger(app_root, ledger)
        once = ledger.read_text(encoding='utf-8')
        write_rejection_ledger(app_root, ledger)

        assert ledger.read_text(encoding='utf-8') == once
        assert once.count(COUNTS_BEGIN) == 1

    def test_the_hand_written_prose_survives(self, tmp_path: Path) -> None:
        app_root = _app_tree(
            tmp_path, "raise ValueError('no recipe here')\n", subdir='cli'
        )
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text('\n'.join(PROSE) + '\n', encoding='utf-8')

        write_rejection_ledger(app_root, ledger)
        write_rejection_ledger(app_root, ledger)

        lines = ledger.read_text(encoding='utf-8').splitlines()
        assert lines[: len(PROSE)] == PROSE

    def test_the_rewrite_names_the_debt_it_took_on_and_retired(
        self, tmp_path: Path
    ) -> None:
        """A total can stay put while one site is paid off and another written.

        The fixture lives under ``app/cli/``, a path no client group claims:
        a regeneration may still take on a sentence there; a client-facing
        one is refused outright (see the refusal tests below).
        """
        app_root = _app_tree(
            tmp_path, "raise ValueError('the old sentence')\n", subdir='cli'
        )
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text('\n'.join(PROSE) + '\n', encoding='utf-8')
        write_rejection_ledger(app_root, ledger)

        (app_root / 'cli' / 'thing_service.py').write_text(
            "raise ValueError('a different sentence')\n", encoding='utf-8'
        )
        rewrite = write_rejection_ledger(app_root, ledger)

        assert rewrite.added == ['app/cli/thing_service.py::a different sentence']
        assert rewrite.removed == ['app/cli/thing_service.py::the old sentence']
        assert ledger_entries(ledger) == {
            'app/cli/thing_service.py::a different sentence'
        }


class TestThePathRuleYieldsToThePerEntryOverride:
    """A group leans per path, and the lean is wrong at a few named places.

    A ``raise`` inside a Pydantic validator in an ``app/api/`` module
    refuses through the 422 RequestValidationError envelope, not the 400
    handler the path rule names; an invitation refusal in a service is
    caught by its endpoint and answered as the translated 404. Those
    places are recorded as per-entry overrides in the generator and must
    be filed by them, not by the directory they sit in.
    """

    def test_validator_sentences_in_api_files_classify_as_422(self) -> None:
        assert (
            rejection_group_for_entry(
                'app/api/organizations.py::Provide exactly one of role or role_id'
            )
            == 'client-422'
        )
        assert (
            rejection_group_for_entry('app/api/stock_lots.py::reason must not be blank')
            == 'client-422'
        )

    def test_a_validator_sentence_in_the_schemas_is_422_debt(self) -> None:
        assert (
            rejection_group_for_entry('app/schemas/user.py::A new validator sentence')
            == 'client-422'
        )

    def test_the_bind_guard_is_not_filed_as_a_validator(self) -> None:
        assert (
            rejection_group_for_entry(
                'app/models/item.py::expected a finite number, got '
            )
            == 'client-guards'
        )

    def test_an_override_cannot_re_file_the_sentences_around_it(self) -> None:
        assert (
            rejection_group_for_entry(
                'app/api/organizations.py::another sentence there'
            )
            == 'client-400'
        )

    def test_the_counts_line_files_the_overridden_entries_under_422(self) -> None:
        counts = counts_by_group(
            {
                'app/api/organizations.py::Provide exactly one of role or role_id',
                'app/api/organizations.py::another sentence there',
            }
        )
        assert counts['client-422'] == 1
        assert counts['client-400'] == 1


class TestTheGeneratorRefusesNewClientFacingDebt:
    """A client-facing sentence may not enter the ledger, switch or no switch.

    The measured shape this pins: one evening in September 2026, two putaway
    validator sentences rode a legitimate regeneration into the ledger
    (424 -> 426) — nobody abused anything, the path was simply open. The
    ledger counts the debt that already exists; it was never meant to be
    the door new client-facing debt walks in through.
    """

    def test_two_new_validator_sentences_are_refused_untouched(
        self, tmp_path: Path
    ) -> None:
        app_root = _app_tree(
            tmp_path,
            "raise ValueError('At least one of product or category must be"
            " set.')\n"
            "raise ValueError('Provide location_ids (ordered) or target"
            "_location_id.')\n",
        )
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text('\n'.join(PROSE) + '\n', encoding='utf-8')

        rewrite = write_rejection_ledger(app_root, ledger)

        assert rewrite.refused == [
            'app/modules/thing_service.py::'
            'At least one of product or category must be set.',
            'app/modules/thing_service.py::'
            'Provide location_ids (ordered) or target_location_id.',
        ]
        assert rewrite.added == [] and rewrite.removed == []
        # The ledger on disk is exactly what it was: a refusal is not a
        # half-write.
        assert ledger_entries(ledger) == set()
        assert ledger.read_text(encoding='utf-8') == '\n'.join(PROSE) + '\n'

    def test_a_new_validator_sentence_in_a_schema_is_refused(
        self, tmp_path: Path
    ) -> None:
        app_root = _app_tree(
            tmp_path, "raise ValueError('Code must be upper case')\n", subdir='schemas'
        )
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text('\n'.join(PROSE) + '\n', encoding='utf-8')

        rewrite = write_rejection_ledger(app_root, ledger)

        assert rewrite.refused == [
            'app/schemas/thing_service.py::Code must be upper case'
        ]
        assert ledger_entries(ledger) == set()

    def test_refusal_survives_an_existing_ledger(self, tmp_path: Path) -> None:
        """Debt already on the books stays; only the first entry is refused."""
        app_root = _app_tree(
            tmp_path, "raise ValueError('the settled sentence')\n", subdir='cli'
        )
        ledger = tmp_path / 'ledger.txt'
        write_rejection_ledger(app_root, ledger)

        (app_root / 'cli' / 'thing_service.py').write_text(
            "raise ValueError('the settled sentence')\n"
            "raise ValueError('a brand new client sentence')\n",
            encoding='utf-8',
        )
        (app_root / 'modules').mkdir()
        (app_root / 'modules' / 'thing_service.py').write_text(
            "raise ValueError('a brand new client sentence')\n",
            encoding='utf-8',
        )
        rewrite = write_rejection_ledger(app_root, ledger)

        # The cli copy was already ledgered; the modules copy of the SAME
        # sentence is new and client-facing — refused, wherever the old one sat.
        assert rewrite.refused == [
            'app/modules/thing_service.py::a brand new client sentence'
        ]

    def test_a_boot_or_cli_sentence_is_not_ledger_debt_when_it_is_an_operator_error(
        self, tmp_path: Path
    ) -> None:
        """No client reads a boot refusal: ``OperatorError`` keeps it out of
        the ledger, while a plain ``ValueError`` at the same place is still
        seen by the scan the gate runs."""
        app_root = _app_tree(
            tmp_path,
            "raise OperatorError('manifest lacks a name')\n",
            subdir='cli',
        )
        assert raw_value_error_sentence_entries(app_root) == set()

        (app_root / 'cli' / 'thing_service.py').write_text(
            "raise ValueError('manifest lacks a name')\n", encoding='utf-8'
        )
        assert raw_value_error_sentence_entries(app_root) == {
            'app/cli/thing_service.py::manifest lacks a name'
        }

    def test_operator_error_is_outside_the_refusal_family(self) -> None:
        trees = [('x.py', ast.parse('class OperatorError(ValueError): pass'))]

        assert 'OperatorError' not in refusal_class_names(trees)


class TestKeyedDynamicRaisesAreVisibleToTheClassification:
    """``ValueError(get_error_message('key', lang))`` carries no literal.

    The raw scan could not see these refusals, so the ledger's numbers read
    as a floor of the refusal surface rather than a count of it. They are
    counted now — and they are classification, not debt: no ledger line,
    no gate asking for one.
    """

    def test_a_keyed_raise_is_counted_and_never_ledgered(self, tmp_path: Path) -> None:
        app_root = tmp_path / 'app'
        (app_root / 'modules').mkdir(parents=True)
        (app_root / 'modules' / 'thing_service.py').write_text(
            'from app.i18n.service import get_error_message\n'
            '\n'
            'def refuse(lang):\n'
            "    raise ValueError(get_error_message('file_too_large', lang))\n",
            encoding='utf-8',
        )
        ledger = tmp_path / 'ledger.txt'
        rewrite = write_rejection_ledger(app_root, ledger)

        assert rewrite.counts['keyed-dynamic'] == 1
        assert rewrite.refused == []
        assert ledger_entries(ledger) == set()

    def test_the_key_literal_names_the_site_when_it_is_written_out(
        self, tmp_path: Path
    ) -> None:
        app_root = tmp_path / 'app'
        (app_root / 'modules').mkdir(parents=True)
        (app_root / 'modules' / 'thing_service.py').write_text(
            'from app.i18n.service import get_error_message\n'
            '\n'
            'def refuse(lang):\n'
            "    raise ValueError(get_error_message('paste_empty', lang))\n",
            encoding='utf-8',
        )

        entries = keyed_dynamic_value_error_entries(app_root)
        assert entries == {'app/modules/thing_service.py::keyed:paste_empty'}

    def test_a_counted_lookup_is_a_keyed_raise_too(self, tmp_path: Path) -> None:
        """The plural lookup is a catalogue lookup: a plain ``ValueError`` of it
        answered VALIDATION_ERROR while the scan, knowing only
        ``get_error_message``, counted it nowhere."""
        app_root = tmp_path / 'app'
        (app_root / 'modules').mkdir(parents=True)
        (app_root / 'modules' / 'thing_service.py').write_text(
            'from app.i18n.service import get_plural_error_message\n'
            '\n'
            'def refuse(lang, missing):\n'
            '    raise ValueError(\n'
            "        get_plural_error_message('lines_missing', len(missing), lang)\n"
            '    )\n',
            encoding='utf-8',
        )

        entries = keyed_dynamic_value_error_entries(app_root)
        assert entries == {'app/modules/thing_service.py::keyed:lines_missing'}

    def test_a_non_literal_key_names_the_helper_instead(self, tmp_path: Path) -> None:
        app_root = tmp_path / 'app'
        (app_root / 'modules').mkdir(parents=True)
        (app_root / 'modules' / 'thing_service.py').write_text(
            'from app.i18n.service import get_error_message\n'
            '\n'
            'def refuse(lang, key):\n'
            '    raise ValueError(get_error_message(key, lang))\n',
            encoding='utf-8',
        )

        entries = keyed_dynamic_value_error_entries(app_root)
        assert entries == {'app/modules/thing_service.py::keyed:get_error_message'}
