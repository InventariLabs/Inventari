"""Git installs must be pinned to a revision.

``git clone --depth=1`` without a ref installs whatever the default branch
happens to point at, so two installs of "the same" module can differ and
nothing records which code actually landed.
"""

from pathlib import Path

import pytest

from app.cli.module_packaging import resolve_source


class TestResolveSourceRequiresRev:
    @pytest.mark.parametrize(
        'source',
        [
            'https://github.com/user/inventari-module-x.git',
            'http://example.com/mod.git',
            'git@github.com:user/mod.git',
        ],
    )
    def test_git_source_without_rev_is_refused(self, source):
        with pytest.raises(ValueError, match='--rev'):
            resolve_source(source)

    def test_error_explains_why(self):
        with pytest.raises(ValueError) as exc:
            resolve_source('https://github.com/user/mod.git')

        assert 'pinned revision' in str(exc.value)


class TestResolveSourceLocalPaths:
    def test_local_directory_needs_no_rev(self, tmp_path: Path):
        path, is_tmp, commit = resolve_source(str(tmp_path))

        assert path == tmp_path.resolve()
        assert is_tmp is False
        # Nothing to pin: a local directory is whatever is on disk right now.
        assert commit is None

    def test_missing_local_path_is_refused(self, tmp_path: Path):
        with pytest.raises(ValueError, match='does not exist'):
            resolve_source(str(tmp_path / 'nope'))

    def test_file_is_not_a_module_source(self, tmp_path: Path):
        target = tmp_path / 'module.yaml'
        target.write_text('name: x')

        with pytest.raises(ValueError, match='not a directory'):
            resolve_source(str(target))


class TestResolveSourceRejectsOptionLikeInput:
    """A rev or URL starting with '-' would be read by git as a flag."""

    def test_option_like_rev(self):
        with pytest.raises(ValueError, match='may not start with'):
            resolve_source(
                'https://github.com/user/mod.git', '--upload-pack=touch /tmp/x'
            )

    def test_option_like_source(self):
        with pytest.raises(ValueError, match='may not start with'):
            resolve_source('--upload-pack=touch /tmp/x.git', 'v1.0.0')


class TestResolveSourceGitCheckout:
    """Clone-and-checkout against a real (local, bare) repository."""

    @staticmethod
    def _bare_repo_with_tag(tmp_path: Path) -> str:
        import shutil
        import subprocess

        git_bin = shutil.which('git')
        assert git_bin, 'git is required for the clone tests'
        work = tmp_path / 'work'
        work.mkdir()
        (work / 'module.yaml').write_text('name: probe\nversion: 0.1.0\n')

        def git(*args: str, cwd: Path = work) -> None:
            subprocess.run(
                [git_bin, *args],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            )

        git('init')
        git('add', '.')
        git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-m', 'probe')
        git('tag', 'v1.0.0')
        bare = str(tmp_path / 'probe.git')
        git('init', '--bare', bare, cwd=tmp_path)
        git('push', bare, 'v1.0.0')
        return bare

    def test_known_tag_resolves(self, tmp_path: Path):
        import shutil

        source = self._bare_repo_with_tag(tmp_path)

        path, is_tmp, commit = resolve_source(source, 'v1.0.0')

        assert is_tmp is True
        assert commit
        assert (path / 'module.yaml').exists()
        shutil.rmtree(path, ignore_errors=True)

    def test_unknown_revision_message_names_only_the_revision(self, tmp_path: Path):
        """git's own checkout failure used to be appended verbatim, and an
        unknown rev makes git argue about a path argument to --detach — a
        problem the user never caused. The message now says what is missing
        and how to look, and stops there."""
        source = self._bare_repo_with_tag(tmp_path)

        with pytest.raises(ValueError) as exc:
            resolve_source(source, 'v9.9.9')

        message = str(exc.value)
        assert "'v9.9.9'" in message
        assert 'not found' in message
        assert 'ls-remote' in message
        assert 'path argument' not in message
        assert 'fatal:' not in message
