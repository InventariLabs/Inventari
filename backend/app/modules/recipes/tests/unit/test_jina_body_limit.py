from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.modules.recipes.scrapers import jina_llm


def test_reader_stops_streaming_at_the_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks_read: list[int] = []

    class Response:
        headers: dict[str, str] = {}
        encoding = 'utf-8'

        def raise_for_status(self) -> None:
            pass

        def iter_raw(self, chunk_size: int) -> Iterator[bytes]:
            for index in range(20):
                chunks_read.append(index)
                yield b'a' * chunk_size

    @contextmanager
    def stream(*args: Any, **kwargs: Any) -> Iterator[Response]:
        yield Response()

    monkeypatch.setattr(jina_llm.httpx, 'stream', stream)

    def unbounded_get(*args: Any, **kwargs: Any) -> None:
        raise AssertionError('the reader must stream its response')

    monkeypatch.setattr(jina_llm.httpx, 'get', unbounded_get)
    monkeypatch.setattr(jina_llm, '_JINA_MAX_BYTES', 32768, raising=False)
    result = jina_llm._fetch_via_jina('https://example.com')
    assert result == 'a' * 32768
    assert len(chunks_read) < 20


def test_reader_rejects_compressed_body_before_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        headers = {'content-encoding': 'gzip'}

        def raise_for_status(self) -> None:
            pass

    @contextmanager
    def stream(*args: Any, **kwargs: Any) -> Iterator[Response]:
        yield Response()

    monkeypatch.setattr(jina_llm.httpx, 'stream', stream)
    with pytest.raises(ValueError, match='compressed content'):
        jina_llm._fetch_via_jina('https://example.com')


def test_reader_falls_back_to_utf8_for_unknown_charset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        headers: dict[str, str] = {}
        encoding = 'unknown-charset'

        def raise_for_status(self) -> None:
            pass

        def iter_raw(self, chunk_size: int) -> Iterator[bytes]:
            yield 'Crème brûlée'.encode()

    @contextmanager
    def stream(*args: Any, **kwargs: Any) -> Iterator[Response]:
        yield Response()

    monkeypatch.setattr(jina_llm.httpx, 'stream', stream)
    assert jina_llm._fetch_via_jina('https://example.com') == 'Crème brûlée'
