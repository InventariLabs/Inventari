"""A commit message is published with the code, so it is held to prose.

The commit-msg hook and the push-side check read a message by the rules the
public-tree scan uses for identifiers and plan vocabulary, plus the ones only a
message needs: a branch name, git's own merge subject, and the maintainers'
private words, which come from a word file outside this repository. An issue
reference and a commit hash name public things and pass. The push-side check
fails only on what would make something private public: a reword after the push
rewrites published history, so wording there is reported, not failed.

The public-tree scan reads this file too, so the identifiers it plants are
assembled at run time (``_id``, or a ``+`` where a pattern would match).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.check_internal_ids import (
    PROSE_DEV_MERGE,
    check_commit_msg_file,
    check_commits,
    load_private_words,
    message_findings,
    ticket_pattern,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
#: A synthetic private prefix next to the public one.
_TICKET = ticket_pattern({'INV': 4, 'ZZQ': 3})


def _id(number: int) -> str:
    """A task identifier under the public prefix, assembled at run time."""
    return f'INV-{number}'


def _kinds(
    text: str,
    *,
    private_words: re.Pattern[str] | None = None,
    repo_root: Path | None = None,
) -> list[str]:
    findings = message_findings(
        text, ticket=_TICKET, private_words=private_words, repo_root=repo_root
    )
    return [what for what, _ in findings]


@pytest.fixture
def private_words(tmp_path: Path) -> re.Pattern[str]:
    path = tmp_path / 'words.txt'
    path.write_text(
        '# the private words, one expression per line\n'
        '\n'
        r'\bquartermasters?\b' + '\n'
        r'\bnightjar-\d[\w.]*' + '\n',
        encoding='utf-8',
    )
    pattern = load_private_words(path)
    assert pattern is not None
    return pattern


class TestWhatAMessageMayNotCarry:
    def test_a_task_identifier_in_any_case(self) -> None:
        assert _kinds(f'fix: the unit follows the record ({_id(12)})') == [
            'a task identifier'
        ]
        assert _kinds(f'fix: the unit follows the record ({_id(12).lower()})') == [
            'a task identifier'
        ]

    def test_an_identifier_from_the_private_prefix_list(self) -> None:
        assert _kinds('The shelf label names its row (ZZQ-7)') == ['a task identifier']

    def test_a_milestone(self) -> None:
        assert _kinds('Close what M-101 left open') == ['a milestone identifier']

    def test_plan_vocabulary(self) -> None:
        assert _kinds('Finish Wave' + ' 2 of the import') == ['plan vocabulary']

    @pytest.mark.parametrize(
        'branch', ['fix/the-shelf-label', 'origin/feature/label-preview', 'feat/x']
    )
    def test_a_branch_name(self, branch: str) -> None:
        assert _kinds(f'Bring {branch} up to date', repo_root=_REPO_ROOT) == [
            'a branch name'
        ]

    def test_private_words_from_the_private_list(
        self, private_words: re.Pattern[str]
    ) -> None:
        text = 'Reword the label\n\nThe Quartermaster asked nightjar-2.1 for it.'
        assert _kinds(text, private_words=private_words) == [
            'private vocabulary',
            'private vocabulary',
        ]

    def test_gits_own_merge_subject_other_than_catching_up_with_dev(self) -> None:
        kinds = _kinds("Merge branch 'fix/shelf-label'", repo_root=_REPO_ROOT)
        assert "git's own merge subject, not prose" in kinds
        assert 'a branch name' in kinds


class TestWhatPasses:
    def test_prose(self, private_words: re.Pattern[str]) -> None:
        text = (
            'fix(labels): the caption keeps its size beside a bigger code\n'
            '\n'
            'A caption label left the code a third of its width although the\n'
            'height allowed more, so scanners at arm length missed it.'
        )
        assert _kinds(text, private_words=private_words) == []

    def test_an_issue_reference_and_a_commit_hash(self) -> None:
        assert _kinds('Fixes #12\n\nThe regression came with 828bb4610.') == []

    def test_a_file_path_is_not_a_branch(self, tmp_path: Path) -> None:
        (tmp_path / 'docs' / 'api').mkdir(parents=True)
        text = 'Regenerate docs/api and drop docs/old-guide.md, now in docs/api/a.json'
        assert _kinds(text, repo_root=tmp_path) == []

    def test_without_a_word_list_private_words_are_not_known(self) -> None:
        assert _kinds('The quartermaster merges it') == []

    def test_comment_lines_and_the_cut_below_the_scissors(self) -> None:
        text = (
            'Keep the caption at its size\n'
            f'# Please enter the commit message ({_id(12)})\n'
            '# ------------------------ >8 ------------------------\n'
            f'diff --git a/x b/x ({_id(13)} on fix/x)\n'
        )
        assert _kinds(text, repo_root=_REPO_ROOT) == []


class TestTheHook:
    def test_refuses_a_message_that_is_not_prose(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        message = tmp_path / 'COMMIT_EDITMSG'
        message.write_text(f'fix: the unit follows the record ({_id(12)})\n')
        assert check_commit_msg_file(message, None) == 1
        assert f'«{_id(12)}»' in capsys.readouterr().out

    def test_lets_prose_through_untouched(self, tmp_path: Path) -> None:
        message = tmp_path / 'COMMIT_EDITMSG'
        text = 'fix: the unit follows the record\n\nFixes #4\n'
        message.write_text(text)
        assert check_commit_msg_file(message, None) == 0
        assert message.read_text() == text

    @pytest.mark.parametrize(
        'subject',
        [
            "Merge remote-tracking branch 'origin/dev' into fix/shelf-label",
            "Merge branch 'dev' of github.com:example/inventari into chore/x",
            "Merge branch 'dev' into feature/y",
        ],
    )
    def test_writes_the_prose_for_catching_up_with_dev(
        self, tmp_path: Path, subject: str
    ) -> None:
        message = tmp_path / 'MERGE_MSG'
        message.write_text(f'{subject}\n\n# Conflicts:\n#\tbackend/app/x.py\n')
        assert check_commit_msg_file(message, None) == 0
        assert message.read_text().splitlines()[0] == PROSE_DEV_MERGE

    def test_refuses_any_other_default_merge_subject(self, tmp_path: Path) -> None:
        message = tmp_path / 'MERGE_MSG'
        message.write_text("Merge branch 'fix/shelf-label'\n")
        assert check_commit_msg_file(message, None) == 1
        assert message.read_text() == "Merge branch 'fix/shelf-label'\n"


class TestTheWordList:
    def test_comments_and_blank_lines_are_not_words(self, tmp_path: Path) -> None:
        path = tmp_path / 'words.txt'
        path.write_text('# a comment\n\n' + r'\bwardens?\b' + '\n')
        pattern = load_private_words(path)
        assert pattern is not None
        assert pattern.search('the Wardens said')
        assert not pattern.search('a comment')

    def test_an_expression_that_does_not_compile_fails_loudly(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / 'words.txt'
        path.write_text('ok\n(unclosed\n')
        with pytest.raises(ValueError, match=r'words\.txt:2'):
            load_private_words(path)

    def test_no_file_means_no_words(self, tmp_path: Path) -> None:
        assert load_private_words(tmp_path / 'missing.txt') is None

    def test_the_file_named_by_the_environment_is_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / 'words.txt'
        path.write_text(r'\bwardens?\b' + '\n')
        monkeypatch.setenv('INVENTARI_PRIVATE_WORDS', str(path))
        pattern = load_private_words()
        assert pattern is not None
        assert pattern.search('a warden')


class TestThePushSide:
    @staticmethod
    def _git() -> str:
        git = shutil.which('git')
        if git is None:
            pytest.skip('git is not installed here')
        return git

    def _commit(self, repo: Path, message: str) -> None:
        (repo / 'f.txt').write_text(message)
        subprocess.run([self._git(), 'add', 'f.txt'], cwd=repo, check=True)
        subprocess.run(
            [
                self._git(),
                '-c',
                'user.name=t',
                '-c',
                'user.email=t@example.com',
                'commit',
                '--no-verify',
                '-qm',
                message,
            ],
            cwd=repo,
            check=True,
        )

    def test_reads_every_commit_the_range_would_publish(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        subprocess.run([self._git(), 'init', '-q'], cwd=tmp_path, check=True)
        self._commit(tmp_path, 'Start the shelf')
        self._commit(tmp_path, f'Name the shelf row ({_id(9)})')
        self._commit(tmp_path, 'Keep the caption at its size')

        assert check_commits('HEAD~2..HEAD', None, repo=tmp_path) == 1
        out = capsys.readouterr().out
        assert 'Name the shelf row' in out
        assert f'«{_id(9)}»' in out
        assert 'Keep the caption' not in out

        assert check_commits('HEAD~1..HEAD', None, repo=tmp_path) == 0

    def test_reports_wording_without_failing_on_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        subprocess.run([self._git(), 'init', '-q'], cwd=tmp_path, check=True)
        self._commit(tmp_path, 'Start the shelf')
        self._commit(
            tmp_path, "Merge remote-tracking branch 'origin/dev' into fix/shelf-label"
        )
        self._commit(tmp_path, 'Bring the shelf label up to date')

        assert check_commits('HEAD~2..HEAD', None, repo=tmp_path) == 0
        out = capsys.readouterr().out
        assert "git's own merge subject" in out
        assert '«fix/shelf-label»' in out
        assert '1 commit(s)' in out


class TestTheHookIsConfigured:
    def test_pre_commit_installs_and_runs_the_message_check(self) -> None:
        config = (_REPO_ROOT / '.pre-commit-config.yaml').read_text(encoding='utf-8')
        assert 'default_install_hook_types: [pre-commit, commit-msg]' in config
        assert 'default_stages: [pre-commit]' in config
        hook = config.split('id: commit-message-prose', 1)[1]
        assert 'check_internal_ids.py --commit-msg' in hook
        assert 'stages: [commit-msg]' in hook
