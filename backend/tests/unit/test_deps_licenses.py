"""The dependency licence gate, tested against metadata that really exists.

Every string below was copied from the metadata of a package the project has
actually installed, because that is where this gate goes wrong: not on tidy
SPDX expressions but on a stray `Other/Proprietary License` classifier, a
tri-licensed package, or `LGPL` read as `GPL`.
"""

from app.cli._deps_licenses import (
    EXCEPTIONS,
    _resolve,
    classify,
    normalize_licence,
    split_expression,
)


class TestNormalizeLicence:
    def test_reads_a_pypi_classifier(self) -> None:
        assert normalize_licence('License :: OSI Approved :: MIT License') == 'MIT'

    def test_lgpl_is_not_read_as_gpl(self) -> None:
        # psycopg2-binary's real classifier. Substring matching gets this wrong
        # and would block a dependency the project legitimately ships.
        raw = 'License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)'
        assert normalize_licence(raw) == 'LGPL'

    def test_unstated_lgpl_version_is_not_invented(self) -> None:
        assert normalize_licence('LGPL with exceptions') == 'LGPL'

    def test_mpl_1_1_is_not_read_as_mpl_2_0(self) -> None:
        raw = 'License :: OSI Approved :: Mozilla Public License 1.1 (MPL 1.1)'
        assert normalize_licence(raw) == 'MPL-1.1'

    def test_mit_zero_is_not_read_as_plain_mit(self) -> None:
        # cffi ships under MIT-0; the report labelled it MIT because the
        # alias table matches by substring and MIT came first.
        assert normalize_licence('MIT-0') == 'MIT-0'
        assert classify(['MIT-0']) == 'allowed'

    def test_unrecognised_text_is_unknown_not_permissive(self) -> None:
        assert normalize_licence('see LICENSE file') == 'UNKNOWN'
        assert normalize_licence('') == 'UNKNOWN'


class TestTheReportDoesNotOverclaim:
    def test_the_header_names_what_it_leaves_out(self) -> None:
        from app.cli._deps_licenses import ScanResult
        from app.cli._deps_licenses_report import render_markdown

        body = render_markdown(ScanResult())
        assert 'Every component' not in body
        for left_out in (
            'base images',
            'psycopg2-binary',
            'seed_assets',
            'print-agent',
        ):
            assert left_out in body


class TestClassify:
    def test_gpl_blocks(self) -> None:
        assert classify(['GPL-2.0']) == 'blocked'

    def test_source_available_licences_block(self) -> None:
        # Redis 7.4+ — the reason the stack runs Valkey.
        assert classify(['RSAL-2.0']) == 'blocked'
        assert classify(['SSPL-1.0']) == 'blocked'

    def test_alternatives_pass_on_the_permissive_option(self) -> None:
        assert classify(['GPL-2.0', 'MIT']) == 'allowed'

    def test_conjunctive_sets_must_satisfy_every_part(self) -> None:
        assert classify(['GPL-2.0', 'MIT'], conjunctive=True) == 'blocked'

    def test_lgpl_needs_a_decision_rather_than_failing_the_build(self) -> None:
        assert classify(['LGPL']) == 'review'

    def test_nothing_declared_needs_a_decision(self) -> None:
        assert classify([]) == 'review'
        assert classify(['UNKNOWN']) == 'review'


class TestSplitExpression:
    def test_or_is_alternatives(self) -> None:
        assert split_expression('MIT OR Apache-2.0') == (['MIT', 'Apache-2.0'], False)

    def test_and_is_conjunctive(self) -> None:
        assert split_expression('MIT AND GPL-3.0') == (['MIT', 'GPL-3.0'], True)

    def test_parentheses_and_separators(self) -> None:
        identifiers, conjunctive = split_expression('(MIT OR CC0-1.0)')
        assert identifiers == ['MIT', 'CC0-1.0']
        assert conjunctive is False


class TestRealPackageMetadata:
    def test_unidecode_would_be_blocked(self) -> None:
        """The finding this gate exists for.

        `unidecode` published exactly this classifier while sitting in the
        runtime set, and nothing read it because a declared dependency is
        not a file in the tree.
        """
        raw = (
            'License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)'
        )
        licence, verdict, _ = _resolve('Unidecode', [normalize_licence(raw)], False)
        assert licence == 'GPL-2.0'
        assert verdict == 'blocked'

    def test_qrcode_bogus_proprietary_classifier_does_not_block(self) -> None:
        candidates = [
            normalize_licence('License :: OSI Approved :: BSD License'),
            normalize_licence('License :: Other/Proprietary License'),
        ]
        licence, verdict, note = _resolve('qrcode', candidates, False)
        assert verdict == 'allowed'
        assert licence == 'BSD-3-Clause'
        assert 'bogus' in note

    def test_pyphen_tri_licence_resolves_to_the_option_we_take(self) -> None:
        candidates = [
            normalize_licence('GNU General Public License v2 or later (GPLv2+)'),
            normalize_licence(
                'GNU Lesser General Public License v2 or later (LGPLv2+)'
            ),
            normalize_licence('Mozilla Public License 1.1 (MPL 1.1)'),
        ]
        licence, verdict, note = _resolve('pyphen', candidates, False)
        assert licence == 'MPL-1.1'
        assert verdict == 'review'
        assert 'tri-licensed' in note

    def test_caniuse_lite_is_attribution_not_a_blocker(self) -> None:
        licence, verdict, note = _resolve('caniuse-lite', ['CC-BY-4.0'], False)
        assert licence == 'CC-BY-4.0'
        assert verdict == 'review'
        assert 'attribution' in note

    def test_anyascii_replacement_is_permissive(self) -> None:
        raw = 'License :: OSI Approved :: ISC License (ISCL)'
        _, verdict, _ = _resolve('anyascii', [normalize_licence(raw)], False)
        assert verdict == 'allowed'


class TestExceptionsAreExplained:
    def test_every_exception_carries_a_reason(self) -> None:
        # A bare name here would be an unexplained hole in the gate.
        for name, (licence, reason) in EXCEPTIONS.items():
            assert licence, name
            assert len(reason) > 20, name
