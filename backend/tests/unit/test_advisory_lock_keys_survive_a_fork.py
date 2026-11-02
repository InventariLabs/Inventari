"""An advisory lock whose key is computed in the process locks nothing.

``pg_advisory_xact_lock`` serialises two transactions only when both name the
same key. Two numbering services built theirs from Python's ``hash()`` on a
string — which is salted per process unless PYTHONHASHSEED is set, and
production starts four workers without setting it. Each worker therefore
computed a different key, took a lock nobody else contended for, read the
highest number in use, and wrote the next one. Two concurrent creations could
land on the same number and collide on the unique index, which is a 500 for
whoever came second.

Nothing about that is visible in a single-process test run: one process
agrees with itself. So this file proves the two halves separately — that
``hash()`` really does move between processes, and that no lock key is built
from it any more.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]

LOCK_KEY_SOURCES = [
    'app/modules/warehouse/document_numbering_service.py',
]

#: The maker used to be here — it carried its own numbering and its own
#: advisory lock, keyed from ``hash()`` like the one above. It now takes its
#: numbers from the document register, which locks its counter row instead, so
#: there is no key left in this file to be wrong about. What would go wrong
#: from here is a private numbering engine coming back, and that is what the
#: last class of this file refuses.
MAKER_THAT_BORROWS_THE_REGISTER = 'app/modules/maker/production_service.py'


def _hash_in(seed: str, value: str) -> int:
    """``hash(value)`` as computed by a fresh interpreter with *seed*."""
    out = subprocess.run(
        [sys.executable, '-c', f'print(hash({value!r}))'],
        capture_output=True,
        text=True,
        check=True,
        env={'PYTHONHASHSEED': seed, 'PATH': '/usr/bin:/bin'},
    )
    return int(out.stdout.strip())


class TestTheSaltIsReal:
    def test_two_processes_disagree_about_hash_of_the_same_string(self) -> None:
        # The premise the old key rested on. If this ever stops being true the
        # rest of this file is still correct, only less urgent.
        assert _hash_in('1', 'IN') != _hash_in('2', 'IN')

    def test_the_same_seed_agrees_with_itself(self) -> None:
        # Which is why a single-process test suite never caught it.
        assert _hash_in('7', 'IN') == _hash_in('7', 'IN')


def _calls_hash_builtin(tree: ast.AST) -> list[int]:
    """Lines where this module calls the ``hash()`` builtin."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'hash'
    ]


@pytest.mark.parametrize('rel', LOCK_KEY_SOURCES)
class TestNumberingLocksAreHashedInTheDatabase:
    def test_the_key_is_not_computed_in_this_process(self, rel: str) -> None:
        tree = ast.parse((BACKEND / rel).read_text(encoding='utf-8'))
        assert _calls_hash_builtin(tree) == [], (
            f'{rel} builds a value with hash(); a lock key built that way is '
            'different in every worker'
        )

    def test_it_does_not_pass_its_own_integer_to_the_lock(self, rel: str) -> None:
        source = (BACKEND / rel).read_text(encoding='utf-8')
        assert 'pg_advisory_xact_lock' not in source


class TestTheMakerBorrowsTheRegistersLock:
    """The maker numbers through the document register or not at all.

    What killed the old key was that it was computed per process. What kept it
    alive was that there were two numbering engines at all — so the maker
    having no lock of its own is the property, and a second engine coming back
    is what turns it red.
    """

    def test_it_has_no_lock_key_of_its_own(self) -> None:
        source = (BACKEND / MAKER_THAT_BORROWS_THE_REGISTER).read_text(encoding='utf-8')
        assert _calls_hash_builtin(ast.parse(source)) == []
        assert 'acquire_advisory_lock' not in source
        assert 'pg_advisory_xact_lock' not in source

    def test_it_takes_its_numbers_from_the_register(self) -> None:
        source = (BACKEND / MAKER_THAT_BORROWS_THE_REGISTER).read_text(encoding='utf-8')
        assert 'generate_number_async' in source
