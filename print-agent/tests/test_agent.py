"""The print agent against a stubbed Inventari API.

Run from print-agent/:
    uv run --with-requirements requirements.txt --with pytest pytest tests

The HTTP side is an httpx.MockTransport, the printer is a real shell command
that copies the PNG it is handed, so a test sees exactly the bytes a printer
would get.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent

_PNG = b'\x89PNG\r\n\x1a\nfake-label-batch'
_EMPTY_POOL = {
    'detail': {
        'code': 'NO_LABELS_AVAILABLE',
        'message': 'No labels available for printing',
    }
}
_SERVER_CONTRACT = (
    Path(__file__).resolve().parents[2]
    / 'backend/app/core/contracts/_system_dtos.py'
)


@pytest.fixture
def printed(tmp_path: Path) -> Path:
    return tmp_path / 'printed.png'


@pytest.fixture
def config(printed: Path) -> dict:
    return {
        'inventari_url': 'https://inventari.test',
        'api_key': 'inv_live_0123456789abcdef',
        'printer_type': 'command',
        'printer_name': '',
        'printer_command': f'cp {{file}} {printed}',
        'printer_dpi': None,
        'printer_max_height_px': None,
        'separate_labels': True,
        'poll_interval': 1,
        'label_width': 50.0,
        'label_height': 24.0,
        'label_columns': None,
        'label_qr_only': False,
        'label_batch_size': 3,
        'agent_name': 'office',
        'queue_interval': 0,
    }


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[httpx.Request]]:
    """Answers every request with one response and records what was asked."""

    def install(status: int = 200, **response: object) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(status, **response)  # type: ignore[arg-type]

        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            agent,
            '_client',
            lambda timeout: httpx.Client(transport=transport, timeout=timeout),
        )
        return seen

    return install


class TestTheKeyTravelsTheWayTheServerReadsIt:
    def test_the_key_goes_in_its_own_header_and_as_a_bearer_token(
        self, server, config
    ) -> None:
        seen = server(content=_PNG)

        agent.fetch_unprinted_labels_png(config)

        assert seen[0].headers['X-API-Key'] == 'inv_live_0123456789abcdef'
        # For a server from before keys had their own header.
        assert seen[0].headers['Authorization'] == 'Bearer inv_live_0123456789abcdef'

    @pytest.mark.skipif(
        not _SERVER_CONTRACT.exists(), reason='the agent is checked out alone'
    )
    def test_the_header_is_the_one_the_server_declares(self) -> None:
        source = _SERVER_CONTRACT.read_text()
        header = re.search(r"^API_KEY_HEADER = '([^']+)'", source, re.M)
        assert header, 'the server no longer declares the key header'

        sent = agent._api_headers({"api_key": "k"})

        assert sent[header.group(1)] == 'k'

    def test_the_request_asks_only_for_what_the_endpoint_reads(
        self, server, config
    ) -> None:
        seen = server(content=_PNG)

        agent.fetch_unprinted_labels_png(config)

        params = dict(seen[0].url.params)
        assert seen[0].url.path == '/api/v1/labels/pool/export/png'
        assert 'unprinted_only' not in params
        assert params['count'] == '3'
        # One label file for every printer: nothing about this one goes up,
        # and a printer with no settings gets the file at its own 300 dpi.
        assert 'media' not in params
        assert 'dpi' not in params


class TestPrintNow:
    def test_it_prints_the_batch_the_server_sends(
        self, server, config, printed
    ) -> None:
        server(content=_PNG)

        agent.cmd_print_now(config)

        assert printed.read_bytes() == _PNG

    def test_an_empty_pool_is_nothing_to_do_not_an_error(
        self, server, config, printed, caplog
    ) -> None:
        server(status=400, json=_EMPTY_POOL)

        with caplog.at_level(logging.INFO, logger='inventari-print-agent'):
            agent.cmd_print_now(config)

        assert not printed.exists()
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert 'nothing to print' in caplog.text.lower()

    def test_a_refused_key_is_reported_and_fails_the_command(
        self, server, config, printed, caplog
    ) -> None:
        server(status=401, json={'detail': 'Not authenticated'})

        with pytest.raises(SystemExit) as exit_info:
            agent.cmd_print_now(config)

        assert exit_info.value.code == 1
        assert not printed.exists()
        assert 'API error 401' in caplog.text
        assert 'nothing to print' not in caplog.text.lower()

    def test_another_validation_error_is_not_mistaken_for_an_empty_pool(
        self, server, config, caplog
    ) -> None:
        server(
            status=400,
            json={'detail': {'code': 'VALIDATION_ERROR', 'message': 'bad media'}},
        )

        with pytest.raises(SystemExit):
            agent.cmd_print_now(config)

        assert 'API error 400' in caplog.text


class TestOneRunCycle:
    def test_a_cycle_prints_what_is_waiting(self, server, config, printed) -> None:
        server(content=_PNG)

        agent.run_cycle(config)

        assert printed.read_bytes() == _PNG

    def test_a_cycle_on_an_empty_pool_says_nothing_to_print_and_nothing_else(
        self, server, config, printed, caplog
    ) -> None:
        server(status=400, json=_EMPTY_POOL)

        with caplog.at_level(logging.INFO):
            agent.run_cycle(config)

        assert not printed.exists()
        assert [r.getMessage() for r in caplog.records] == [
            'No unprinted labels: nothing to print.'
        ]

    def test_a_cycle_survives_an_unreachable_server(
        self, monkeypatch, config, printed, caplog
    ) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError('connection refused', request=request)

        transport = httpx.MockTransport(refuse)
        monkeypatch.setattr(
            agent,
            '_client',
            lambda timeout: httpx.Client(transport=transport, timeout=timeout),
        )

        agent.run_cycle(config)

        assert not printed.exists()
        assert 'Network error' in caplog.text


# ---------------------------------------------------------------------------
# serve: the print queue
# ---------------------------------------------------------------------------

_JOB = {
    'id': 'job-1',
    'count': 2,
    'width_mm': 50.0,
    'height_mm': 24.0,
    'lease_until': '2026-10-06T21:00:00Z',
    'attempt': 3,
}


@pytest.fixture
def queue_server(monkeypatch: pytest.MonkeyPatch):
    """A stub of the print-queue endpoints, answering by path."""

    def install(routes: dict[str, Callable[[httpx.Request], httpx.Response]]):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            path = request.url.path.removeprefix('/api/v1/printing/agent')
            return routes[f'{request.method} {path}'](request)

        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            agent,
            '_client',
            lambda timeout: httpx.Client(transport=transport, timeout=timeout),
        )
        return seen

    return install


@pytest.fixture(autouse=True)
def nothing_printed_unreported(monkeypatch: pytest.MonkeyPatch) -> None:
    """What one test printed and could not report is not another test's."""
    monkeypatch.setattr(agent, '_printed_unreported', {})


def _reports(seen: list[httpx.Request]) -> list[dict]:
    return [json.loads(r.content) for r in seen if r.url.path.endswith('/report')]


def _job_routes(**overrides):
    routes = {
        'POST /agent-1/claim': lambda r: httpx.Response(200, json=_JOB),
        'GET /jobs/job-1/image': lambda r: httpx.Response(200, content=_PNG),
        'POST /jobs/job-1/report': lambda r: httpx.Response(200, json={}),
    }
    routes.update(overrides)
    return routes


class TestServe:
    def test_registering_names_the_printer_and_what_this_agent_speaks(
        self, queue_server, config
    ) -> None:
        config['agent_name'] = 'garage'
        seen = queue_server(
            {'POST /register': lambda r: httpx.Response(200, json={'id': 'agent-1'})}
        )

        agent_id = agent.register_agent(config)

        assert agent_id == 'agent-1'
        assert json.loads(seen[0].content) == {
            'name': 'garage',
            'printer_type': 'command',
            'agent_version': agent.AGENT_VERSION,
            'protocol_version': agent.PROTOCOL_VERSION,
        }

    def test_a_job_is_printed_and_reported_printed(
        self, queue_server, config, printed
    ) -> None:
        seen = queue_server(_job_routes())

        took = agent.serve_cycle(config, 'agent-1')

        assert took is True
        # A printer with no settings prints the file as it came, and is not
        # asked for anything about it.
        assert printed.read_bytes() == _PNG
        [image_request] = [r for r in seen if r.url.path.endswith('/image')]
        assert dict(image_request.url.params) == {}
        assert _reports(seen) == [
            {'agent_id': 'agent-1', 'attempt': 3, 'printed': True, 'error': None}
        ]

    def test_a_printer_failure_is_reported_with_its_reason(
        self, queue_server, config, printed
    ) -> None:
        config['printer_command'] = 'echo "tape jammed" >&2; exit 3'
        seen = queue_server(_job_routes())

        agent.serve_cycle(config, 'agent-1')

        [report] = _reports(seen)
        assert report['printed'] is False
        assert 'exit 3' in report['error']
        assert 'tape jammed' in report['error']
        assert not printed.exists()

    def test_nothing_waiting_asks_for_nothing_more(self, queue_server, config) -> None:
        seen = queue_server(
            {'POST /agent-1/claim': lambda r: httpx.Response(204)}
        )

        took = agent.serve_cycle(config, 'agent-1')

        assert took is False
        assert len(seen) == 1

    def test_a_server_gone_mid_job_gets_no_report_and_nothing_prints(
        self, queue_server, config, printed
    ) -> None:
        def vanish(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError('connection reset', request=request)

        seen = queue_server(_job_routes(**{'GET /jobs/job-1/image': vanish}))

        with pytest.raises(agent.ApiError):
            agent.serve_cycle(config, 'agent-1')

        assert not printed.exists()
        assert _reports(seen) == []

    def test_a_printed_job_whose_report_failed_is_reported_not_printed_again(
        self, queue_server, config, printed
    ) -> None:
        """The labels are on paper; the server did not hear it.

        The job's lease runs out and it comes back. Printing it again would
        put a second set of the same labels on the desk.
        """
        queue_server(
            _job_routes(
                **{'POST /jobs/job-1/report': lambda r: httpx.Response(503)}
            )
        )
        with pytest.raises(agent.ApiError):
            agent.serve_cycle(config, 'agent-1')
        assert printed.read_bytes() == _PNG
        printed.unlink()

        again = {**_JOB, 'attempt': 4}
        seen = queue_server(
            _job_routes(
                **{'POST /agent-1/claim': lambda r: httpx.Response(200, json=again)}
            )
        )
        took = agent.serve_cycle(config, 'agent-1')

        assert took is True
        assert not printed.exists()
        assert not [r for r in seen if r.url.path.endswith('/image')]
        assert _reports(seen) == [
            {'agent_id': 'agent-1', 'attempt': 4, 'printed': True, 'error': None}
        ]

    def test_the_webhook_listener_is_gone(self) -> None:
        assert not hasattr(agent, 'cmd_listen')


# ---------------------------------------------------------------------------
# The handshake: what this agent is, and the protocol it speaks
# ---------------------------------------------------------------------------

#: Where the server declares its protocol versions, when the two are checked
#: out together.
_SERVER_SCHEMAS = (
    Path(__file__).resolve().parents[2] / 'backend/app/modules/printing/schemas.py'
)


class TestTheHandshakeSaysWhatThisAgentSpeaks:
    @pytest.mark.skipif(
        not _SERVER_SCHEMAS.exists(), reason='the agent is checked out alone'
    )
    def test_the_protocol_is_one_the_server_still_speaks(self) -> None:
        source = _SERVER_SCHEMAS.read_text()
        newest = re.search(r'^PROTOCOL_VERSION = (\d+)', source, re.M)
        oldest = re.search(r'^PROTOCOL_MIN_VERSION = (\d+)', source, re.M)
        assert newest and oldest, 'the server no longer declares its protocol versions'

        assert int(oldest.group(1)) <= agent.PROTOCOL_VERSION <= int(newest.group(1))

    def test_a_server_on_another_protocol_draws_a_warning(
        self, queue_server, config, caplog
    ) -> None:
        queue_server(
            {
                'POST /register': lambda r: httpx.Response(
                    200,
                    json={
                        'id': 'agent-1',
                        'server_protocol_version': agent.PROTOCOL_VERSION + 1,
                    },
                )
            }
        )

        with caplog.at_level(logging.INFO, logger='inventari-print-agent'):
            agent.register_agent(config)

        assert 'protocol' in caplog.text.lower()
        assert str(agent.PROTOCOL_VERSION + 1) in caplog.text

    def test_a_server_that_speaks_the_same_protocol_is_nothing_to_warn_about(
        self, queue_server, config, caplog
    ) -> None:
        queue_server(
            {
                'POST /register': lambda r: httpx.Response(
                    200,
                    json={
                        'id': 'agent-1',
                        'server_protocol_version': agent.PROTOCOL_VERSION,
                    },
                )
            }
        )

        with caplog.at_level(logging.INFO, logger='inventari-print-agent'):
            agent.register_agent(config)

        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    def test_a_server_from_before_the_versioned_protocol_draws_one_too(
        self, queue_server, config, caplog
    ) -> None:
        queue_server(
            {'POST /register': lambda r: httpx.Response(200, json={'id': 'agent-1'})}
        )

        with caplog.at_level(logging.INFO, logger='inventari-print-agent'):
            agent.register_agent(config)

        assert [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert 'protocol' in caplog.text.lower()

    def test_a_refusal_is_printed_in_the_servers_own_words(
        self, queue_server, config, monkeypatch, caplog
    ) -> None:
        """What the server refuses, the agent prints: its message, not a code."""
        queue_server(
            {
                'POST /register': lambda r: httpx.Response(
                    400,
                    json={
                        'detail': {
                            'code': 'PRINT_AGENT_PROTOCOL_UNSUPPORTED',
                            'message': (
                                'This agent speaks print protocol 2; this server '
                                'speaks print protocol 1. Update the print agent.'
                            ),
                        }
                    },
                )
            }
        )
        monkeypatch.setattr(agent.time, 'sleep', lambda seconds: sys.exit(0))

        with caplog.at_level(logging.INFO, logger='inventari-print-agent'):
            with pytest.raises(SystemExit):
                agent.cmd_serve(config)

        assert 'This agent speaks print protocol 2' in caplog.text
        # The words, not the body they arrived in.
        assert '{"detail"' not in caplog.text


# ---------------------------------------------------------------------------
# The interpreter it runs on
# ---------------------------------------------------------------------------


class TestItRefusesToStartBelowItsPythonFloor:
    def test_it_says_what_it_needs_and_stops(self, tmp_path: Path) -> None:
        """Not a TypeError on an annotation: a message naming the floor."""
        starter = tmp_path / 'start.py'
        starter.write_text('import sys\nsys.version_info = (3, 9, 18)\nimport agent\n')

        result = subprocess.run(
            [sys.executable, str(starter)],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                'PYTHONPATH': str(Path(agent.__file__).resolve().parent),
            },
        )

        assert result.returncode != 0
        assert '3.11' in result.stderr

    def test_the_floor_is_the_one_the_readme_states(self) -> None:
        readme = (Path(agent.__file__).resolve().parent / 'README.md').read_text()

        assert f'Python {agent.PYTHON_FLOOR[0]}.{agent.PYTHON_FLOOR[1]}' in readme


# ---------------------------------------------------------------------------
# A Brother P-touch: the label at the head's raster, 1-bit
# ---------------------------------------------------------------------------

#: What ptouch-print 1.7 says about a PT-P710BT with a 24 mm cassette.
_INFO_24MM = """PT-P710BT found on USB bus 1, device 9
maximum printing width for this printer is 128px
maximum printing width for this tape is 128px
media type = 0x01 (Laminated tape)
media width = 24 mm
tape color = 0x01 (White)
text color = 0x08 (Black)
error = 0x0000
"""
_NO_PRINTER = 'No P-Touch printer found on USB (remember to put switch to position E)'


def _grey_label() -> bytes:
    """A small greyscale label: black, a mid grey on each side of 128, white."""
    image = Image.new('L', (8, 4), color=255)
    for x, value in enumerate((0, 100, 160, 255)):
        image.putpixel((x, 0), value)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


@pytest.fixture
def ptouch_info(monkeypatch: pytest.MonkeyPatch):
    """What ``ptouch-print --info`` answers; the real one talks to USB."""

    def install(stdout: str = '', stderr: str = '', returncode: int = 0) -> list:
        calls: list = []

        def fake_run(args, **kwargs):
            calls.append(args)
            assert args == ['ptouch-print', '--info'], args
            return subprocess.CompletedProcess(args, returncode, stdout, stderr)

        monkeypatch.setattr(agent.subprocess, 'run', fake_run)
        return calls

    return install


@pytest.fixture
def brother(config: dict, printed: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A Brother whose print command copies the PNG instead of printing it."""
    # One strip, as these tests were written; the separate-labels tests turn
    # the setting on for themselves.
    config.update(printer_type='brother-p710bt', printer_dpi=180.0, separate_labels=False)
    monkeypatch.setattr(agent, 'print_png_reporting', _copying_to(printed))
    return config


def _copying_to(printed: Path):
    def copy(image_data: bytes, config: dict, flags: str = '') -> str | None:
        printed.write_bytes(image_data)
        return None

    return copy


class TestABrotherGetsTheLabelAtItsRaster:
    def test_the_tape_is_read_from_the_printer(self, ptouch_info) -> None:
        ptouch_info(stdout=_INFO_24MM)

        assert agent.brother_tape_dots() == 128

    def test_the_label_is_asked_for_at_180_dpi_within_the_tape(
        self, queue_server, ptouch_info, brother, printed
    ) -> None:
        ptouch_info(stdout=_INFO_24MM)
        job = {**_JOB, 'height_mm': 18.0}
        seen = queue_server(
            _job_routes(
                **{
                    'POST /agent-1/claim': lambda r: httpx.Response(200, json=job),
                    'GET /jobs/job-1/image': lambda r: httpx.Response(
                        200, content=_grey_label()
                    ),
                }
            )
        )

        agent.serve_cycle(brother, 'agent-1')

        [image_request] = [r for r in seen if r.url.path.endswith('/image')]
        # The tape leaves white edges of its own, so a bare QR may fill the
        # 128 dots across it.
        assert dict(image_request.url.params) == {
            'dpi': '180.0',
            'max_height_px': '128',
            'edge_to_edge': 'true',
        }
        # A thermal head prints a dot or none: the label reaches it 1-bit,
        # split at the midpoint.
        sent = Image.open(io.BytesIO(printed.read_bytes()))
        assert sent.mode == '1'
        assert [sent.getpixel((x, 0)) for x in range(4)] == [0, 0, 255, 255]
        # 18 mm at 180 dpi is 128 dots: it printed at its size.
        assert _reports(seen) == [
            {'agent_id': 'agent-1', 'attempt': 3, 'printed': True, 'error': None}
        ]

    def test_a_label_taller_than_the_tape_reports_how_much_it_shrank(
        self, queue_server, ptouch_info, brother
    ) -> None:
        """50 x 24 on 24 mm tape: the head prints 18 mm of it."""
        ptouch_info(stdout=_INFO_24MM)
        seen = queue_server(
            _job_routes(
                **{
                    'GET /jobs/job-1/image': lambda r: httpx.Response(
                        200, content=_grey_label()
                    )
                }
            )
        )

        agent.serve_cycle(brother, 'agent-1')

        [report] = _reports(seen)
        assert report['printed'] is True
        assert report['scale'] == 0.753

    def test_a_printer_that_does_not_answer_fails_the_job_with_its_words(
        self, queue_server, ptouch_info, brother, printed
    ) -> None:
        ptouch_info(stderr=_NO_PRINTER, returncode=5)
        seen = queue_server(_job_routes())

        took = agent.serve_cycle(brother, 'agent-1')

        assert took is True
        assert not printed.exists()
        assert not [r for r in seen if r.url.path.endswith('/image')]
        [report] = _reports(seen)
        assert report['printed'] is False
        assert 'tape' in report['error']
        assert _NO_PRINTER in report['error']

    def test_the_pool_is_printed_at_the_same_raster(
        self, server, ptouch_info, brother
    ) -> None:
        ptouch_info(stdout=_INFO_24MM)
        seen = server(content=_grey_label())

        agent.run_cycle(brother)

        params = dict(seen[0].url.params)
        assert (params['dpi'], params['max_height_px']) == ('180.0', '128')
        assert params['edge_to_edge'] == 'true'


class TestABrotherPrintsAJobApart:
    """Several labels come out cut apart, the lead paid once per job."""

    @pytest.fixture
    def printed_flags(self, brother: dict, monkeypatch, ptouch_info) -> list[str]:
        brother['separate_labels'] = True
        ptouch_info(stdout=_INFO_24MM)
        flags: list[str] = []

        def record(image_data: bytes, config: dict, given: str = '') -> str | None:
            flags.append(given)
            return None

        monkeypatch.setattr(agent, 'print_png_reporting', record)
        return flags

    @staticmethod
    def _routes(count: int, **overrides):
        job = {**_JOB, 'count': count}
        return _job_routes(
            **{
                'POST /agent-1/claim': lambda r: httpx.Response(200, json=job),
                'GET /jobs/job-1/image': lambda r: httpx.Response(200, content=_grey_label()),
                **overrides,
            }
        )

    def test_the_command_puts_the_options_before_the_image(self, brother) -> None:
        assert agent._get_print_command(brother, '--chain --precut ') == 'ptouch-print --chain --precut --image {file}'
        assert agent._get_print_command(brother) == 'ptouch-print --image {file}'

    def test_every_label_but_the_last_chains_and_every_one_but_the_first_precuts(self) -> None:
        assert [agent.chain_flags(i, 3) for i in range(3)] == [
            '--chain ',
            '--chain --precut ',
            '--precut ',
        ]
        assert agent.chain_flags(0, 1) == ''

    def test_a_job_of_three_is_three_prints_in_order_and_one_report(
        self, queue_server, brother, printed_flags
    ) -> None:
        seen = queue_server(self._routes(3))

        took = agent.serve_cycle(brother, 'agent-1')

        assert took is True
        assert printed_flags == ['--chain ', '--chain --precut ', '--precut ']
        asked = [dict(r.url.params)['index'] for r in seen if r.url.path.endswith('/image')]
        assert asked == ['0', '1', '2']
        [report] = _reports(seen)
        assert report['printed'] is True

    def test_a_failure_stops_the_job_and_names_the_label(
        self, queue_server, brother, monkeypatch, ptouch_info
    ) -> None:
        brother['separate_labels'] = True
        ptouch_info(stdout=_INFO_24MM)
        calls: list[str] = []

        def second_fails(image_data: bytes, config: dict, given: str = '') -> str | None:
            calls.append(given)
            return 'Print command failed (exit 1): tape jammed' if len(calls) == 2 else None

        monkeypatch.setattr(agent, 'print_png_reporting', second_fails)
        seen = queue_server(self._routes(3))

        agent.serve_cycle(brother, 'agent-1')

        assert len(calls) == 2
        assert len([r for r in seen if r.url.path.endswith('/image')]) == 2
        [report] = _reports(seen)
        assert report['printed'] is False
        assert report['error'].startswith('Label 2 of 3: ')
        assert 'tape jammed' in report['error']

    def test_a_label_that_cannot_be_fetched_mid_job_is_reported_not_left_to_reprint(
        self, queue_server, brother, printed_flags
    ) -> None:
        def second_missing(request: httpx.Request) -> httpx.Response:
            if request.url.params['index'] == '1':
                return httpx.Response(500, text='boom')
            return httpx.Response(200, content=_grey_label())

        seen = queue_server(self._routes(3, **{'GET /jobs/job-1/image': second_missing}))

        agent.serve_cycle(brother, 'agent-1')

        assert printed_flags == ['--chain ']
        [report] = _reports(seen)
        assert report['printed'] is False
        assert report['error'].startswith('Label 2 of 3 could not be fetched')

    def test_a_single_label_job_prints_plainly(self, queue_server, brother, printed_flags) -> None:
        seen = queue_server(self._routes(1))

        agent.serve_cycle(brother, 'agent-1')

        assert printed_flags == ['']
        [image_request] = [r for r in seen if r.url.path.endswith('/image')]
        assert 'index' not in image_request.url.params

    def test_the_setting_gives_back_one_strip(self, queue_server, brother, printed_flags) -> None:
        brother['separate_labels'] = False
        seen = queue_server(self._routes(3))

        agent.serve_cycle(brother, 'agent-1')

        assert printed_flags == ['']
        [image_request] = [r for r in seen if r.url.path.endswith('/image')]
        assert 'index' not in image_request.url.params

    def test_another_printer_keeps_the_strip(self, queue_server, config, printed) -> None:
        seen = queue_server(self._routes(3))

        agent.serve_cycle(config, 'agent-1')

        [image_request] = [r for r in seen if r.url.path.endswith('/image')]
        assert 'index' not in image_request.url.params
        assert printed.exists()

    def test_the_setting_is_on_unless_turned_off(self, monkeypatch) -> None:
        monkeypatch.setenv('INVENTARI_URL', 'https://inventari.test')
        monkeypatch.setenv('INVENTARI_API_KEY', 'inv_live_0123456789abcdef')
        monkeypatch.delenv('SEPARATE_LABELS', raising=False)
        assert agent.get_config('serve')['separate_labels'] is True
        monkeypatch.setenv('SEPARATE_LABELS', 'false')
        assert agent.get_config('serve')['separate_labels'] is False


class TestThePrintersSettings:
    def test_a_brother_is_180_dpi_unless_told_otherwise(self, monkeypatch) -> None:
        monkeypatch.setenv('PRINTER_TYPE', 'brother-p710bt')
        monkeypatch.delenv('PRINTER_DPI', raising=False)
        assert agent._printer_dpi() == 180.0

        monkeypatch.setenv('PRINTER_DPI', '360')
        assert agent._printer_dpi() == 360.0

    def test_any_other_printer_takes_the_file_at_its_own_resolution(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv('PRINTER_TYPE', 'cups')
        monkeypatch.delenv('PRINTER_DPI', raising=False)
        assert agent._printer_dpi() is None

    def test_a_printer_told_its_reach_is_asked_for_a_label_within_it(
        self, config
    ) -> None:
        config.update(printer_dpi=203.0, printer_max_height_px=384)

        assert agent.printer_raster(config) == {'dpi': 203.0, 'max_height_px': 384}

    def test_a_label_within_reach_is_not_reported_as_shrunk(self) -> None:
        assert agent.shrink_scale(18.0, {'dpi': 180.0, 'max_height_px': 128}) is None
        assert agent.shrink_scale(24.0, {'dpi': 180.0}) is None
        assert agent.shrink_scale(None, {'dpi': 180.0, 'max_height_px': 128}) is None

    def test_a_label_a_hair_too_tall_is_not_reported_as_shrunk(self) -> None:
        """24 mm at 180 dpi is 170.08 dots: on a head of 170 it prints at 99.95%.

        Rounded to three places that was a scale of 1, which the server
        refused after the label had printed.
        """
        assert agent.shrink_scale(24.0, {'dpi': 180.0, 'max_height_px': 170}) is None
        assert agent.shrink_scale(24.0, {'dpi': 180.0, 'max_height_px': 168}) == 0.988


class TestServeReadsNoLabelSize:
    """In serve mode the label's size comes with the job, chosen in the app.

    A pool setting left in the .env — even a broken one — must not stop the
    printer from coming online.
    """

    @pytest.fixture
    def env(self, monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
        monkeypatch.setenv('INVENTARI_URL', 'https://inventari.test')
        monkeypatch.setenv('INVENTARI_API_KEY', 'inv_live_0123456789abcdef')
        for name in ('LABEL_WIDTH', 'LABEL_HEIGHT', 'LABEL_BATCH_SIZE', 'POLL_INTERVAL'):
            monkeypatch.setenv(name, 'unused-invalid')
        return monkeypatch

    def test_serve_starts_with_the_pool_settings_broken(self, env) -> None:
        config = agent.get_config('serve')

        assert not any(key.startswith('label_') for key in config)
        assert 'poll_interval' not in config

    def test_the_pool_modes_still_read_the_label_size(self, env) -> None:
        env.setenv('LABEL_WIDTH', '62')
        env.setenv('LABEL_HEIGHT', '29')
        env.setenv('LABEL_BATCH_SIZE', '10')
        env.setenv('POLL_INTERVAL', '5')

        for command in ('run', 'print-now'):
            config = agent.get_config(command)
            assert (config['label_width'], config['label_height']) == (62.0, 29.0)
