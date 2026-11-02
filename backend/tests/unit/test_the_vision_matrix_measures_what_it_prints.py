"""The vision matrix harness, held to the two claims its tables make.

``scripts/vision_model_matrix.py`` produced the tables in
``docs/subsystems/VISION_AI.md`` and had no test at all, which is how both of
these got out: the A/B switch never reached the call it was meant to vary, so
the "flag sent / flag not sent" table came from code that is not in the
repository; and "fields read is out of 32 for everyone, including the
photographs a model declined to answer" was true of the prose and not of the
tool, whose denominator counted only the answered ones.

Neither has a production caller to notice — the harness is the only consumer
of its own numbers — so the numbers are what the tests hold.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

_HARNESS = Path(__file__).resolve().parents[2] / 'scripts' / 'vision_model_matrix.py'


def _harness() -> Any:
    spec = importlib.util.spec_from_file_location('vision_model_matrix', _HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Session:
    """Enough of a session for the harness: a connection to rename, no I/O."""

    def __init__(self) -> None:
        self.connection = SimpleNamespace(model_name='before')

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def get(self, _model: Any, _id: Any) -> Any:
        return self.connection

    async def commit(self) -> None:
        return None


class _Database:
    def AsyncSessionLocal(self) -> _Session:  # noqa: N802 - mirrors the real name
        return _Session()


_CORPUS = [
    {
        'barcode': '1111111111111',
        'note': 'front with everything on it',
        'expected': {
            'name': 'Pesto',
            'brand': 'Barilla',
            'weight': '190 g',
            'expiry_date': None,
        },
    },
    {
        'barcode': '2222222222222',
        'note': 'front the model will refuse',
        'expected': {
            'name': 'Nesquik',
            'brand': 'Nestle',
            'weight': None,
            'expiry_date': None,
        },
    },
]
_IMAGES = {entry['barcode']: b'jpeg' for entry in _CORPUS}


@pytest.mark.unit
class TestTheHarnessMeasuresWhatItPrints:
    async def test_the_reasoning_switch_reaches_the_call_it_varies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``--keep-reasoning`` has to arrive at the extraction, not stop here.

        ``measure_model`` took the flag and called ``run_one`` without it, so
        both halves of the A/B measured the same thing while the result file
        recorded two different settings.
        """
        harness = _harness()
        seen: list[bool] = []

        async def fake_run_one(
            _db: Any,
            _org: Any,
            _user: Any,
            _image: bytes,
            *,
            disable_reasoning: bool = True,
        ) -> tuple[dict[str, Any] | None, str | None]:
            seen.append(disable_reasoning)
            return {'name': None, 'brand': None}, None

        async def fake_tokens(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'cost_usd': 0.0,
                'provider_calls': 1,
            }

        monkeypatch.setattr(harness, 'run_one', fake_run_one)
        monkeypatch.setattr(harness, 'tokens_since', fake_tokens)

        await harness.measure_model(
            _Database(),
            uuid4(),
            uuid4(),
            uuid4(),
            'some/model',
            _CORPUS,
            _IMAGES,
            disable_reasoning=False,
        )

        assert seen == [False, False]

    async def test_a_refused_photograph_is_still_measured_out_of_the_corpus(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Declining a photograph may not improve a model's reading score.

        Five fields are legible across this corpus, three of them on the
        photograph the model answered. It read all three and refused the
        other picture, so it scores three of five on the corpus and three of
        three on what it answered. Both denominators are printed, and they
        are not the same number.
        """
        harness = _harness()
        answers = iter(
            [
                ({'name': 'Pesto', 'brand': 'Barilla', 'weight': '190 g'}, None),
                (None, 'LlmTransportError: ReadTimeout'),
            ]
        )

        async def fake_run_one(*_args: Any, **_kwargs: Any) -> Any:
            return next(answers)

        async def fake_tokens(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'cost_usd': 0.0,
                'provider_calls': 1,
            }

        monkeypatch.setattr(harness, 'run_one', fake_run_one)
        monkeypatch.setattr(harness, 'tokens_since', fake_tokens)

        summary = await harness.measure_model(
            _Database(),
            uuid4(),
            uuid4(),
            uuid4(),
            'some/model',
            _CORPUS,
            _IMAGES,
        )

        assert summary['answered'] == 1
        assert summary['of_images'] == 2
        assert summary['read'] == 3
        assert summary['legible'] == 5
        assert summary['answered_legible'] == 3

        table = harness.as_markdown({'models': {'some/model': summary}})
        assert '| 3/5 | 3/3 |' in table
