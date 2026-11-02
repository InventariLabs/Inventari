"""Regenerating the refusal ledger: first generation, refusal of new debt, CLI.

The refusal gate is only as good as its ledger discipline: the first
generation takes the debt as it stands, every later one may retire entries
but must refuse a new sentence, and the command line says which of the two
happened and exits accordingly.
"""

import ast
from pathlib import Path

import pytest

from app.core.architecture_lint import _main
from app.core.architecture_lint._quality_checks_rejections import (
    COUNTS_BEGIN,
    ledger_entries,
    refusal_class_names,
    write_refusal_ledger,
)

PROSE = ['# Ledger of refusal sentences.', '# A line here is debt, never permission.']
ONE = "raise HTTPException(status_code=409, detail='Period is closed.')\n"
TWO = ONE + "raise HTTPException(status_code=400, detail='Quantity is wrong.')\n"


def _app_tree(tmp_path: Path, body: str) -> Path:
    modules = tmp_path / 'app' / 'modules'
    modules.mkdir(parents=True)
    (modules / 'thing.py').write_text(body, encoding='utf-8')
    return tmp_path / 'app'


class TestRefusalLedgerRewrite:
    def test_the_first_generation_takes_the_debt_as_it_stands(
        self, tmp_path: Path
    ) -> None:
        app_root = _app_tree(tmp_path, TWO)
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text('\n'.join(PROSE) + '\n', encoding='utf-8')

        rewrite = write_refusal_ledger(app_root, ledger)

        assert rewrite.refused == []
        assert rewrite.counts == {'refusals': 2}
        assert len(rewrite.added) == 2
        assert ledger_entries(ledger) == {
            'app/modules/thing.py::Period is closed.',
            'app/modules/thing.py::Quantity is wrong.',
        }
        lines = ledger.read_text(encoding='utf-8').splitlines()
        assert lines[: len(PROSE)] == PROSE
        assert lines.count(COUNTS_BEGIN) == 1

    def test_a_new_sentence_is_refused_and_the_file_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        app_root = _app_tree(tmp_path, ONE)
        ledger = tmp_path / 'ledger.txt'
        write_refusal_ledger(app_root, ledger)
        before = ledger.read_bytes()
        _app_tree_rewrite(app_root, TWO)

        rewrite = write_refusal_ledger(app_root, ledger)

        assert rewrite.refused == ['app/modules/thing.py::Quantity is wrong.']
        assert ledger.read_bytes() == before

    def test_a_paid_off_sentence_is_retired(self, tmp_path: Path) -> None:
        app_root = _app_tree(tmp_path, TWO)
        ledger = tmp_path / 'ledger.txt'
        write_refusal_ledger(app_root, ledger)
        _app_tree_rewrite(app_root, ONE)

        rewrite = write_refusal_ledger(app_root, ledger)

        assert rewrite.refused == []
        assert rewrite.removed == ['app/modules/thing.py::Quantity is wrong.']
        assert ledger_entries(ledger) == {'app/modules/thing.py::Period is closed.'}


def _app_tree_rewrite(app_root: Path, body: str) -> None:
    (app_root / 'modules' / 'thing.py').write_text(body, encoding='utf-8')


class TestRefusalLedgerCommand:
    """``--write-rejection-ledger`` regenerates both ledgers, then the refusal one."""

    @pytest.fixture
    def tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        app_root = _app_tree(tmp_path, ONE)
        refusal = tmp_path / 'refusals.txt'
        rejection = tmp_path / 'rejections.txt'
        rejection.write_text('\n'.join(PROSE) + '\n', encoding='utf-8')
        monkeypatch.setattr(_main, 'MODULES_ROOT', app_root / 'modules')
        monkeypatch.setattr(_main, 'REFUSAL_LEDGER_FILE', refusal)
        monkeypatch.setattr(_main, 'REJECTION_LEDGER_FILE', rejection)
        return app_root

    @staticmethod
    def _run() -> int | None:
        args = _main.build_parser().parse_args(['--write-rejection-ledger'])
        return _main._run_write_modes(args)

    def test_the_first_run_writes_the_refusal_ledger_and_exits_zero(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._run() == 0

        out = capsys.readouterr().out
        assert 'Regenerated the refusal ledger' in out
        assert '+ app/modules/thing.py::Period is closed.' in out
        assert ledger_entries(_main.REFUSAL_LEDGER_FILE) == {
            'app/modules/thing.py::Period is closed.'
        }

    def test_a_retired_sentence_is_printed_as_removed(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _app_tree_rewrite(tree, TWO)
        write_refusal_ledger(tree, _main.REFUSAL_LEDGER_FILE)
        _app_tree_rewrite(tree, ONE)

        assert self._run() == 0

        assert '- app/modules/thing.py::Quantity is wrong.' in capsys.readouterr().out

    def test_a_new_sentence_fails_the_command(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_refusal_ledger(tree, _main.REFUSAL_LEDGER_FILE)
        _app_tree_rewrite(tree, TWO)
        before = _main.REFUSAL_LEDGER_FILE.read_bytes()

        assert self._run() == 1

        out = capsys.readouterr().out
        assert 'Refused to regenerate the refusal ledger' in out
        assert '! app/modules/thing.py::Quantity is wrong.' in out
        assert _main.REFUSAL_LEDGER_FILE.read_bytes() == before


def test_a_cycle_in_the_class_graph_does_not_loop() -> None:
    tree = ast.parse('class A(B): ...\nclass B(A): ...\nclass C(ValueError): ...\n')

    names = refusal_class_names([('x.py', tree)])

    assert 'C' in names
    assert not {'A', 'B'} & names
