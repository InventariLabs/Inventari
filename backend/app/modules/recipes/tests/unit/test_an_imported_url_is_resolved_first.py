"""A recipe URL is checked against the address it actually reaches.

``_validate_external_url`` read the hostname and stopped there: a literal
``127.0.0.1`` was refused, but ``metadata.example.com`` — a name whose owner
points it at ``169.254.169.254`` — walked straight through, and the importer
fetched it. The cover downloader on the neighbouring path already resolves
and pins the address; this one now uses the same guard.

The JSON-LD scraper is the second half. It fetches a user-supplied URL with
no guard at all, validating only the target of a redirect. It has no caller
today — the pipeline goes through Jina — and is kept on purpose (it carries
a vulture whitelist entry with an owner and an expiry), which is exactly what
makes it worth guarding rather than leaving as a wire-up away from an SSRF.
"""

from __future__ import annotations

import socket

import pytest
from fastapi import HTTPException

from app.modules.recipes._router_crud import _validate_external_url

_LINK_LOCAL = '169.254.169.254'
_PUBLIC = '93.184.216.34'


def _resolves_to(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    def _fake(
        *_args: object, **_kwargs: object
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]

    monkeypatch.setattr(socket, 'getaddrinfo', _fake)


class TestTheImportUrlIsResolved:
    def test_a_name_pointing_at_the_metadata_service_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _resolves_to(monkeypatch, _LINK_LOCAL)

        with pytest.raises(HTTPException) as exc:
            _validate_external_url('https://metadata.example.com/recipe')

        assert exc.value.status_code == 400

    def test_a_name_pointing_at_the_loopback_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _resolves_to(monkeypatch, '127.0.0.2')

        with pytest.raises(HTTPException) as exc:
            _validate_external_url('https://inside.example.com/recipe')

        assert exc.value.status_code == 400

    def test_a_name_that_does_not_resolve_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not a free pass: the fetch would resolve the name a second time."""

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise socket.gaierror('Name or service not known')

        monkeypatch.setattr(socket, 'getaddrinfo', _boom)

        with pytest.raises(HTTPException) as exc:
            _validate_external_url('https://nowhere.example/recipe')

        assert exc.value.status_code == 400

    def test_the_literals_are_still_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _resolves_to(monkeypatch, _PUBLIC)  # never reached for a literal

        for url in (
            'http://127.0.0.1/recipe',
            'http://192.168.0.10/recipe',
            'http://localhost/recipe',
        ):
            with pytest.raises(HTTPException):
                _validate_external_url(url)

    def test_a_url_without_a_host_is_refused(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _validate_external_url('https:///recipe')

        assert exc.value.status_code == 400

    def test_a_public_address_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _resolves_to(monkeypatch, _PUBLIC)

        _validate_external_url('https://example.com/recipe')
