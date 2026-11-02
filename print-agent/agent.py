#!/usr/bin/env python3
"""
Inventari Print Agent
=====================
A standalone daemon that bridges your Inventari instance with a
physical label printer.

Usage:
    python agent.py --help
    python agent.py serve                        # Print what the app sends to this printer
    python agent.py run                          # Print the pool of blank labels as it fills
    python agent.py print-now                    # One-shot: print unprinted pool labels
    python agent.py test-printer                 # Test printer connection

Configuration (environment variables or .env file):
    INVENTARI_URL        Base URL of your Inventari instance (e.g. https://my.inventari.app)
    INVENTARI_API_KEY    API key generated in Inventari → Settings → API Keys
                         (a key with the "printing" scope can do nothing else)
    PRINTER_TYPE         brother-p710bt | cups | command
    PRINTER_NAME         CUPS printer name (for PRINTER_TYPE=cups)
    PRINTER_COMMAND      Shell command template with {file} placeholder
    PRINTER_DPI          The printer's resolution; the label is drawn at it
                         (default: 180 for a Brother, else the file's 300)
    PRINTER_MAX_HEIGHT_PX  Dots the printer prints across; a taller label is
                         scaled down to fit (a Brother reads it from its tape)
    SEPARATE_LABELS      brother-p710bt: print a job's labels one by one, cut apart
                         (default: true); false prints a job as one strip
    AGENT_NAME           The name this printer has in the app (default: host name)
    QUEUE_INTERVAL       Seconds between asks for work in serve mode (default: 3)
    POLL_INTERVAL        Seconds between polls in run mode (default: 30)
    LABEL_WIDTH          Label width in mm, run and print-now (default: 50)
    LABEL_HEIGHT         Label height in mm, run and print-now (default: 24)
    LABEL_COLUMNS        Labels per row in batch PNG (default: auto)
    LABEL_QR_ONLY        Print QR only, no text (default: false)
    LABEL_BATCH_SIZE     Max labels per poll cycle (default: 50)

In serve mode the label's size is the one chosen in the app; the agent only
fits that label to its printer.
"""

import io
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

#: The oldest Python this agent runs on — the floor the README states. Below
#: it the annotations in this file raise TypeError one by one; this says what
#: is needed and stops.
PYTHON_FLOOR = (3, 11)

if sys.version_info < PYTHON_FLOOR:
    sys.exit(
        f'The Inventari print agent needs Python {PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]} '
        f'or newer; this is Python {sys.version.split()[0]}.'
    )

#: This agent's own release, said at registration and recorded by the server,
#: so an installation can tell one agent from another. Raise it when the agent
#: changes.
AGENT_VERSION = '1.0.0'

#: The printing protocol this agent speaks. The server refuses an agent whose
#: protocol it does not speak, and answers with the protocol it speaks: a gap
#: the two can still work across is a warning here, not a stop.
PROTOCOL_VERSION = 1

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('inventari-print-agent')
# httpx logs every request at info, so each poll of an empty pool would read
# '400 Bad Request' beside the agent's own 'nothing to print'. The agent says
# what a response meant itself; httpx speaks up only for its own warnings.
logging.getLogger('httpx').setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        logger.error(f'Required environment variable {key} is not set.')
        sys.exit(1)
    return value


def _is_brother(printer_type: str) -> bool:
    return printer_type.startswith('brother')


def _printer_dpi() -> float | None:
    """The resolution to ask the server to draw the label at, if not its own.

    A P-touch head is 180 dpi. Drawn at 300 and resampled to it, a QR's
    modules land on two dots and three in turn; drawn at 180 they are whole
    dots. Without a setting any other printer gets the 300 dpi file, which
    states its resolution, and its driver does the rest.
    """
    stated = os.getenv('PRINTER_DPI')
    if stated:
        return float(stated)
    return 180.0 if _is_brother(os.getenv('PRINTER_TYPE', '').lower()) else None


def _printer_max_height_px() -> int | None:
    stated = os.getenv('PRINTER_MAX_HEIGHT_PX')
    return int(stated) if stated else None


#: The modes that print the blank-label pool and so need its settings.
_POOL_COMMANDS = ('run', 'print-now')


def get_config(command: str) -> dict:
    """The settings ``command`` uses, and only those.

    The label's size, columns and batch belong to the blank-label pool. In
    serve mode the size comes with each job, chosen in the app, so a pool
    setting left in the .env is never read there and cannot keep the printer
    from coming online.
    """
    config = {
        'inventari_url': _require_env('INVENTARI_URL').rstrip('/'),
        'api_key': _require_env('INVENTARI_API_KEY'),
        'printer_type': os.getenv('PRINTER_TYPE', '').lower(),
        'printer_name': os.getenv('PRINTER_NAME', ''),
        'printer_command': os.getenv('PRINTER_COMMAND', ''),
        'printer_dpi': _printer_dpi(),
        'printer_max_height_px': _printer_max_height_px(),
        'separate_labels': os.getenv('SEPARATE_LABELS', 'true').lower() != 'false',
        'agent_name': os.getenv('AGENT_NAME') or socket.gethostname(),
        'queue_interval': float(os.getenv('QUEUE_INTERVAL', '3')),
    }
    if command in _POOL_COMMANDS:
        config.update(
            poll_interval=int(os.getenv('POLL_INTERVAL', '30')),
            label_width=float(os.getenv('LABEL_WIDTH', '50')),
            label_height=float(os.getenv('LABEL_HEIGHT', '24')),
            label_columns=os.getenv('LABEL_COLUMNS'),
            label_qr_only=os.getenv('LABEL_QR_ONLY', 'false').lower() == 'true',
            label_batch_size=int(os.getenv('LABEL_BATCH_SIZE', '50')),
        )
    return config


# ---------------------------------------------------------------------------
# Printer drivers
# ---------------------------------------------------------------------------


def _print_with_command(image_path: str, command_template: str) -> str | None:
    """Run the print command; None when it succeeded, else what went wrong."""
    cmd = command_template.replace('{file}', image_path)
    logger.info(f'Running: {cmd}')
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)  # noqa: S602
        if result.stdout:
            logger.info(f'Output: {result.stdout.strip()}')
        return None
    except subprocess.CalledProcessError as exc:
        reason = f'Print command failed (exit {exc.returncode}): {exc.stderr.strip()}'
        logger.error(reason)
        return reason


def _get_print_command(config: dict, flags: str = '') -> str:
    """Returns the shell command template for the configured printer type.

    ``flags`` are options of ptouch-print that go before the image they apply
    to; no other printer reads them.
    """
    ptype = config['printer_type']

    if ptype == 'brother-p710bt':
        return f'ptouch-print {flags}--image {{file}}'

    if ptype == 'cups':
        name = config['printer_name']
        if name:
            return f'lpr -P {name} {{file}}'
        return 'lpr {file}'

    if ptype == 'command':
        if not config['printer_command']:
            logger.error('PRINTER_COMMAND must be set when PRINTER_TYPE=command')
            sys.exit(1)
        return config['printer_command']

    logger.error(
        f"Unknown PRINTER_TYPE '{ptype}'. "
        'Supported values: brother-p710bt, cups, command'
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Fitting the label to this printer
# ---------------------------------------------------------------------------
#
# The server draws one label file for every printer: W x H mm at the size the
# person chose in the app. What a printer needs from that file is this
# agent's business, next to the printer — the server knows nothing of it.


class PrinterError(Exception):
    """The printer could not be asked what it holds."""


#: What ``ptouch-print --info`` says about the cassette in a P-touch.
_TAPE_DOTS = re.compile(r'maximum printing width for this tape is (\d+)\s*px')


def brother_tape_dots() -> int:
    """How many dots the head prints across the tape now in the printer.

    Read from the printer, not configured: a 24 mm cassette prints 128 dots
    (18 mm), a 12 mm one 64, and swapping the cassette changes the answer.
    """
    try:
        result = subprocess.run(
            ['ptouch-print', '--info'],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrinterError(f'Could not ask the printer about its tape: {exc}') from exc
    found = _TAPE_DOTS.search(result.stdout)
    if not found:
        said = (result.stderr or result.stdout).strip()[:200] or 'no answer'
        raise PrinterError(f'The printer did not say what tape it holds: {said}')
    return int(found.group(1))


def printer_raster(config: dict) -> dict:
    """What to ask the server for: this printer's resolution and its reach.

    Empty for a printer with no settings: it gets the 300 dpi file, which
    carries its own resolution, and its driver prints it at its size.
    """
    raster: dict = {}
    if config['printer_dpi']:
        raster['dpi'] = config['printer_dpi']
    if _is_brother(config['printer_type']):
        raster['max_height_px'] = brother_tape_dots()
        # The tape is wider than the head prints, so it leaves a white edge
        # above and below every label: a bare QR needs none of its own there.
        raster['edge_to_edge'] = True
    elif config['printer_max_height_px']:
        raster['max_height_px'] = config['printer_max_height_px']
    return raster


def shrink_scale(height_mm: float | None, raster: dict) -> float | None:
    """The share of its size a label prints at, when the printer cannot hold it.

    The server scales a label taller than ``max_height_px`` down as a whole;
    this is the same arithmetic, so the agent can say so without measuring
    the image. None when the label printed at its size — also when it was a
    hair too tall: 24 mm on a head 170 dots tall prints at 99.95%, which
    nobody would call shrunk, and rounded to three places it reads as 1.
    """
    if not height_mm or 'max_height_px' not in raster:
        return None
    natural_px = height_mm / 25.4 * raster.get('dpi', 300.0)
    scale = raster['max_height_px'] / natural_px
    if round(scale * 100) >= 100:
        return None
    return round(scale, 3)


def fit_for_printer(image_data: bytes, config: dict) -> bytes:
    """The label as this printer can take it.

    A thermal head prints a dot or no dot, and ptouch-print takes only a
    two-colour PNG, so a Brother gets the label 1-bit. Thresholding at the
    midpoint keeps strokes solid; dithering would print text as a cloud.
    Any other printer gets the file as it came, greys and all.
    """
    if not _is_brother(config['printer_type']):
        return image_data
    from PIL import Image

    grey = Image.open(io.BytesIO(image_data)).convert('L')
    bilevel = grey.point(lambda p: 0 if p < 128 else 255, '1')
    buffer = io.BytesIO()
    bilevel.save(buffer, format='PNG')
    return buffer.getvalue()


def print_png_reporting(image_data: bytes, config: dict, flags: str = '') -> str | None:
    """Print a PNG; None when it printed, else the reason it did not."""
    command = _get_print_command(config, flags)
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp.write(image_data)
        tmp_path = tmp.name

    try:
        return _print_with_command(tmp_path, command)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def chain_flags(position: int, count: int) -> str:
    """ptouch-print's options for label ``position`` (from 0) of ``count``.

    A P-touch pulls its tape through the cutter before every print, so each
    separate print starts with a blank lead as long as the distance from head
    to cutter. Chained, the labels follow one another on the tape: every label
    but the last skips the final feed and cut, and every label but the first
    cuts before itself, so the lead is paid once per job.
    """
    flags = ''
    if position < count - 1:
        flags += '--chain '
    if position > 0:
        flags += '--precut '
    return flags


def print_job_apart(job: dict, raster: dict, config: dict, fetch) -> str | None:
    """Print a job label by label, cut apart; None when all printed.

    A failure names the label it stopped at, so the person knows how many came
    out: the ones before it are on the tape already.
    """
    count = job['count']
    for position in range(count):
        try:
            image = fetch({**raster, 'index': position})
        except ApiError as exc:
            if position == 0:
                raise
            # The earlier labels are printed: reporting beats a lease that
            # runs out and prints them all a second time.
            return f'Label {position + 1} of {count} could not be fetched: {exc}'
        failure = print_png_reporting(fit_for_printer(image, config), config, chain_flags(position, count))
        if failure is not None:
            return f'Label {position + 1} of {count}: {failure}'
    return None


def print_png(image_data: bytes, config: dict) -> bool:
    """Write PNG to a temp file and send it to the printer."""
    return print_png_reporting(image_data, config) is None


# ---------------------------------------------------------------------------
# Inventari API client
# ---------------------------------------------------------------------------


class ApiError(Exception):
    """Inventari could not be reached, or refused the request."""


#: What the export answers when the pool holds nothing unprinted: a 400 whose
#: detail carries this code. Any other 400 is a real refusal.
_EMPTY_POOL_CODE = 'NO_LABELS_AVAILABLE'


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout)


def _api_headers(config: dict) -> dict:
    # The key's own header is what the server reads first. The Bearer form is
    # all a server from before that header understands, so it rides along:
    # a newer server reads X-API-Key and never looks at the bearer copy.
    key = config['api_key']
    return {'X-API-Key': key, 'Authorization': f'Bearer {key}'}


def _is_empty_pool(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        detail = response.json().get('detail')
    except ValueError:
        return False
    return isinstance(detail, dict) and detail.get('code') == _EMPTY_POOL_CODE


def _refusal_text(response: httpx.Response) -> str:
    """What the server refused, in its own words — its message, not its body.

    A refusal is the one thing a person at the printer reads and acts on
    ("update the print agent"), so the agent prints the sentence the server
    wrote rather than the JSON it arrived in.
    """
    try:
        detail = response.json().get('detail')
    except ValueError:
        detail = None
    if isinstance(detail, dict):
        detail = detail.get('message')
    return detail if isinstance(detail, str) and detail else response.text[:200]


def fetch_unprinted_labels_png(config: dict) -> bytes | None:
    """Downloads a PNG batch of unprinted labels from Inventari.

    Returns None when there is nothing to print and raises ApiError when the
    server cannot be reached or refuses, so a refused key is never reported
    as an empty pool. The labels are drawn at this printer's raster, and
    PrinterError says the printer could not be asked for it.
    """
    params = {
        'count': config['label_batch_size'],
        'width': config['label_width'],
        'height': config['label_height'],
        'qr_only': str(config['label_qr_only']).lower(),
        **printer_raster(config),
    }
    if config['label_columns']:
        params['columns'] = config['label_columns']

    url = f"{config['inventari_url']}/api/v1/labels/pool/export/png"
    try:
        with _client(30) as client:
            response = client.get(url, params=params, headers=_api_headers(config))
    except httpx.RequestError as exc:
        raise ApiError(f'Network error reaching Inventari: {exc}') from exc

    if _is_empty_pool(response):
        return None
    if response.is_error:
        raise ApiError(f'API error {response.status_code}: {_refusal_text(response)}')
    return response.content


def test_api_connection(config: dict) -> bool:
    """Verifies that the API key is valid by hitting the /api/v1/modules/status endpoint."""
    url = f"{config['inventari_url']}/api/v1/modules/status"
    try:
        with _client(10) as client:
            response = client.get(url, headers=_api_headers(config))
        if response.status_code == 200:
            logger.info('✅ API connection OK')
            return True
        logger.warning(f'API returned HTTP {response.status_code} — check your API key.')
        return False
    except httpx.RequestError as exc:
        logger.error(f'Cannot reach Inventari at {config["inventari_url"]}: {exc}')
        return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_print_now(config: dict) -> None:
    """One-shot: fetch unprinted labels and print them immediately."""
    logger.info('Fetching unprinted labels…')
    try:
        png = fetch_unprinted_labels_png(config)
    except (ApiError, PrinterError) as exc:
        logger.error(str(exc))
        sys.exit(1)
    if png is None:
        logger.info('No unprinted labels: nothing to print.')
        return

    logger.info(f'Received PNG ({len(png)} bytes), sending to printer…')
    success = print_png(fit_for_printer(png, config), config)
    if success:
        logger.info('✅ Print job sent successfully.')
    else:
        logger.error('❌ Print job failed.')
        sys.exit(1)


def run_cycle(config: dict) -> None:
    """One poll: print whatever is waiting, log and carry on when it fails."""
    try:
        png = fetch_unprinted_labels_png(config)
    except (ApiError, PrinterError) as exc:
        logger.error(str(exc))
        return
    if png is None:
        logger.info('No unprinted labels: nothing to print.')
        return
    logger.info(f'Found unprinted labels ({len(png)} bytes), printing…')
    if print_png(fit_for_printer(png, config), config):
        logger.info('✅ Batch printed.')
    else:
        logger.warning('⚠️  Print failed — will retry next cycle.')


def cmd_run(config: dict) -> None:
    """Start the polling daemon."""
    interval = config['poll_interval']
    logger.info(
        f'Starting Inventari Print Agent (polling every {interval}s, '
        f'printer: {config["printer_type"] or "NOT SET"})'
    )

    if not config['printer_type']:
        logger.error('PRINTER_TYPE is not configured. Set it to: brother-p710bt, cups, or command')
        sys.exit(1)

    while True:
        try:
            run_cycle(config)
        except Exception:
            logger.exception('Unexpected error in poll cycle')

        time.sleep(interval)


def cmd_test_printer(config: dict) -> None:
    """Create a minimal 1×1 white PNG and send it to the printer as a connectivity test."""
    from PIL import Image

    logger.info(f'Testing printer: {config["printer_type"]}')
    img = Image.new('1', (100, 48), color=1)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    png = buf.read()

    success = print_png(png, config)
    if success:
        logger.info('✅ Test page sent.')
    else:
        logger.error('❌ Test failed.')
        sys.exit(1)


# ---------------------------------------------------------------------------
# Print queue (serve mode)
# ---------------------------------------------------------------------------
#
# The app sends chosen labels to a named printer; this agent asks the server
# for that printer's next job, prints exactly those labels and reports how it
# went. The agent always calls the server, never the other way round, so it
# works behind a home router with no port opened. Labels count as printed
# only when the report says so — a jam leaves them unprinted, and the job can
# be sent again from the app.


def _queue_url(config: dict, path: str) -> str:
    return f"{config['inventari_url']}/api/v1/printing/agent{path}"


def _call(config: dict, method: str, path: str, **kwargs) -> httpx.Response:
    try:
        with _client(30) as client:
            response = client.request(
                method, _queue_url(config, path), headers=_api_headers(config), **kwargs
            )
    except httpx.RequestError as exc:
        raise ApiError(f'Network error reaching Inventari: {exc}') from exc
    if response.is_error:
        raise ApiError(f'API error {response.status_code}: {_refusal_text(response)}')
    return response


def register_agent(config: dict) -> str:
    """Announce this printer to Inventari; returns its id there.

    Name, type and what this agent speaks: the label's size is chosen in the
    app and comes with each job, and fitting it to this printer happens here.
    The answer carries the protocol the server speaks — a gap this pair still
    works across is a warning below, and one it cannot cross the server
    refuses before this returns.
    """
    response = _call(
        config,
        'POST',
        '/register',
        json={
            'name': config['agent_name'],
            'printer_type': config['printer_type'],
            'agent_version': AGENT_VERSION,
            'protocol_version': PROTOCOL_VERSION,
        },
    )
    registered = response.json()
    spoken = registered.get('server_protocol_version')
    if spoken != PROTOCOL_VERSION:
        logger.warning(
            f'⚠️  Protocol mismatch: this agent speaks print protocol '
            f'{PROTOCOL_VERSION}, the server speaks '
            f'{spoken or "none (it is older than the versioned protocol)"}. '
            'They still work together; update the older one.'
        )
    return registered['id']


def _report(
    config: dict,
    agent_id: str,
    job: dict,
    failure: str | None,
    scale: float | None = None,
) -> None:
    body = {
        'agent_id': agent_id,
        'attempt': job['attempt'],
        'printed': failure is None,
        'error': failure,
    }
    if scale is not None:
        body['scale'] = scale
    _call(config, 'POST', f'/jobs/{job["id"]}/report', json=body)


#: Jobs this process printed but could not report, with the scale they
#: printed at. Their lease runs out on the server and they come back; they
#: are reported then, not printed a second time.
_printed_unreported: dict[str, float | None] = {}


def serve_cycle(config: dict, agent_id: str) -> bool:
    """Take one job if one waits, print it, report. True when a job was taken.

    A server that disappears mid-job gets no report: the job's lease runs out
    on the server and it is handed out again, so nothing is lost and nothing
    is counted as printed that was not. A job that printed and whose report
    did not get through is remembered, and when it is handed out again it is
    reported without printing — only a restart in between prints it twice.
    The report names the claim's attempt, so a stalled process cannot answer
    for a claim handed out again since.
    """
    claim = _call(config, 'POST', f'/{agent_id}/claim')
    if claim.status_code == 204:
        return False
    job = claim.json()
    if job['id'] in _printed_unreported:
        _report(config, agent_id, job, None, _printed_unreported[job['id']])
        del _printed_unreported[job['id']]
        logger.info(f'✅ Job {job["id"]} was printed before; reported now.')
        return True
    logger.info(f'Job {job["id"]}: {job["count"]} label(s), fetching the image…')
    try:
        raster = printer_raster(config)
    except PrinterError as exc:
        # Nothing printed and nothing fetched: the labels stay unprinted, and
        # the app shows why next to the job.
        _report(config, agent_id, job, str(exc))
        logger.warning(f'⚠️  Job {job["id"]} failed and was reported: {exc}')
        return True

    def fetch(params: dict) -> bytes:
        return _call(config, 'GET', f'/jobs/{job["id"]}/image', params=params).content

    if config['separate_labels'] and _is_brother(config['printer_type']) and job['count'] > 1:
        failure = print_job_apart(job, raster, config, fetch)
    else:
        failure = print_png_reporting(fit_for_printer(fetch(raster), config), config)
    scale = shrink_scale(job.get('height_mm'), raster) if failure is None else None
    try:
        _report(config, agent_id, job, failure, scale)
    except ApiError:
        if failure is None:
            _printed_unreported[job['id']] = scale
        raise
    if failure is not None:
        logger.warning(f'⚠️  Job {job["id"]} failed and was reported: {failure}')
    elif scale is not None:
        logger.warning(
            f'⚠️  Job {job["id"]} printed at {scale:.0%} of its size: the label '
            'is taller than this printer prints.'
        )
    else:
        logger.info(f'✅ Job {job["id"]} printed.')
    return True


def cmd_serve(config: dict) -> None:
    """Print what the app sends to this printer, until stopped."""
    if not config['printer_type']:
        logger.error('PRINTER_TYPE is not configured. Set it to: brother-p710bt, cups, or command')
        sys.exit(1)
    interval = config['queue_interval']
    agent_id = None
    logger.info(
        f'Starting Inventari Print Agent as "{config["agent_name"]}" '
        f'({config["printer_type"]})'
    )
    while True:
        try:
            if agent_id is None:
                agent_id = register_agent(config)
                logger.info(f'Registered; asking for work every {interval:g}s.')
            if serve_cycle(config, agent_id):
                continue
        except ApiError as exc:
            logger.error(str(exc))
            # A printer removed in the app answers 404: register again.
            if 'API error 404' in str(exc):
                agent_id = None
        except Exception:
            logger.exception('Unexpected error while serving the print queue')
        time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description='Inventari Print Agent — local printer bridge',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('serve', help='Print what the app sends to this printer')
    subparsers.add_parser('run', help='Print the pool of blank labels as it fills')
    subparsers.add_parser('print-now', help='One-shot: print unprinted pool labels now')
    subparsers.add_parser('test-printer', help='Send a test page to the printer')

    args = parser.parse_args()
    config = get_config(args.command)

    if args.command == 'serve':
        cmd_serve(config)
    elif args.command == 'run':
        cmd_run(config)
    elif args.command == 'print-now':
        cmd_print_now(config)
    elif args.command == 'test-printer':
        cmd_test_printer(config)


if __name__ == '__main__':
    main()
