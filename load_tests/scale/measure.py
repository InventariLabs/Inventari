#!/usr/bin/env python3
"""Measure Inventari at warehouse scale: every daily screen and report against a budget.

Run against a stack whose organization ``backend/seed_scale_data.py`` seeded
(``make seed-scale``), with nothing else running on the machine. Three halves:

1. **Server time of reads.** Every request named in ``reads()`` — the product
   list with search, filter, sort and a deep page, scans, a shelf's stock, the
   location tree and the occupancy map, To do, the journal, stock as of a past
   date, the statistics and the reconciliation, the product picker as it is
   typed into — is sent ``--runs`` times after one warm-up, and its p50 and
   p95 are kept. Time is the wall time of the whole answer, read to its last
   byte on the same host, so it is the server's time plus a loopback hop.
2. **Writes.** A purchase order of 200 lines received and the receipt undone,
   five dispatches picked together, a stock take of one shelf counted and
   closed, a spreadsheet export, and an import of ``--import-rows`` rows.
3. **The phone.** ``frontend/scripts/measure-scale-screens.mjs`` opens every
   screen on the phone profile of the phone budget and records when it is
   usable and what it downloaded; the GET requests it saw are then timed on
   the server like the reads above, so each screen has its server time too.

Budgets (the task that asked for this measurement set them): lookups and
lists 300 ms p95, reports 2 s p95, a 200-line write 2 s, a screen usable on
the phone within its phone budget (``frontend/scripts/phone-budget.json``;
8 s for a screen that file does not name). Bulk work — the full export and
the import — is measured and has no budget.

Usage (stdlib only; from the repository root):

    python3 load_tests/scale/measure.py --api http://127.0.0.1:8000 --tier 100k \\
        --out load_tests/scale/results/100k.json
    python3 load_tests/scale/measure.py --report load_tests/scale/results/*.json

The halves can run on two machines into one file: a half skipped now keeps
what the file already holds. The server's own host measures the reads and the
writes with ``--skip-browser``; a machine with a browser, reaching the backend
through a tunnel, adds the screens with ``--skip-reads --skip-writes``; and
``--retime FILE`` on the server's host times the screens' requests again
there, so no server time carries the tunnel's round trip.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'frontend'

BUDGET_MS = {'lookup': 300, 'list': 300, 'report': 2000, 'write': 2000}
PHONE_DEFAULT_MS = 8000
#: The screens of ``phone-budget.json``, by the name this measurement gives them.
PHONE_BUDGET_SCREENS = {
    'launcher': 'launcher',
    'todo': 'start',
    'receive': 'receive',
    'issue': 'issue',
    'history': 'history',
    'products': 'products',
}
#: Requests a screen sends that are the shell's, not the screen's.
SHELL_PATHS = ('/api/v1/auth/',)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


class Api:
    """One keep-alive connection to the backend, signed in, re-signed on a 401."""

    def __init__(self, base: str, email: str, password: str, pace: float = 0.0):
        parts = urlsplit(base)
        self.base = base.rstrip('/')
        self.host, self.port = parts.hostname, parts.port or 80
        self.email, self.password = email, password
        self.conn = http.client.HTTPConnection(self.host, self.port, timeout=900)
        self.token = ''
        # Seconds between the starts of two requests: a server whose rate
        # limiter stays on (200 a minute by default) is measured below it.
        self.pace, self.last_sent, self.retry_after = pace, 0.0, None
        self.login()

    def login(self) -> None:
        status, body, _ = self._send(
            'POST',
            '/api/v1/auth/login',
            urlencode({'username': self.email, 'password': self.password}).encode(),
            {'content-type': 'application/x-www-form-urlencoded'},
            auth=False,
        )
        if status != 200:
            raise SystemExit(f'login failed: {status} {body[:200]!r}')
        self.token = json.loads(body)['access_token']

    def _send(self, method, path, body=None, headers=None, auth=True):
        headers = dict(headers or {})
        if auth:
            headers['authorization'] = f'Bearer {self.token}'
        for attempt in range(2):
            try:
                time.sleep(max(0.0, self.last_sent + self.pace - time.perf_counter()))
                self.last_sent = began = time.perf_counter()
                self.conn.request(method, path, body=body, headers=headers)
                response = self.conn.getresponse()
                data = response.read()
                self.retry_after = response.getheader('retry-after')
                return response.status, data, (time.perf_counter() - began) * 1000
            except (http.client.HTTPException, OSError):
                self.conn.close()
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=900)
                if attempt:
                    raise
        raise AssertionError('unreachable')

    def call(self, method, path, payload=None, raw=None, content_type=None):
        """``(status, parsed or raw body, ms)`` — one call, signed in again on a 401."""
        body, headers = None, {}
        if payload is not None:
            body, headers = json.dumps(payload).encode(), {'content-type': 'application/json'}
        elif raw is not None:
            body, headers = raw, {'content-type': content_type}
        try:
            status, data, ms = self._send(method, path, body, headers)
        except (http.client.HTTPException, OSError) as error:
            # The server dropped the connection: a worker killed mid-answer
            # (for memory, most often) is a result to record, not a crash.
            return 0, f'connection lost: {error}', 0.0, 0
        if status == 401:
            self.login()
            status, data, ms = self._send(method, path, body, headers)
        for _ in range(2):
            if status != 429:
                break
            # A route with a limit of its own (a label scan: 30 a minute):
            # wait the window out and time the answer that comes.
            time.sleep(float(self.retry_after or 60) + 1)
            status, data, ms = self._send(method, path, body, headers)
        try:
            parsed = json.loads(data) if data[:1] in (b'{', b'[') else data
        except ValueError:
            parsed = data
        return status, parsed, ms, len(data)

    def get(self, path):
        status, data, _, _ = self.call('GET', path)
        if status != 200:
            raise RuntimeError(f'GET {path}: {status} {str(data)[:300]}')
        return data


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile: the value at or below which ``p`` of them lie."""
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))
    return ordered[int(rank) - 1]


def time_get(api: Api, path: str, runs: int) -> dict:
    """p50/p95 of ``runs`` GETs after one warm-up; fewer runs for a slow answer."""
    status, _, first, size = api.call('GET', path)
    if status != 200:
        return {'status': status, 'error': True, 'bytes': size}
    if first > 10_000:
        runs = min(runs, 3)
    elif first > 2_000:
        runs = min(runs, 5)
    times = []
    for _ in range(runs):
        status, _, ms, size = api.call('GET', path)
        times.append(ms)
    return {
        'status': status,
        'runs': runs,
        'p50': round(percentile(times, 50), 1),
        'p95': round(percentile(times, 95), 1),
        'max': round(max(times), 1),
        'bytes': size,
    }


# --------------------------------------------------------------------------- #
# The organization the seed wrote
# --------------------------------------------------------------------------- #


def seeded_uuid(org: str, kind: str, n: int) -> str:
    """The id ``seed_scale_data.py`` gives a row (``pg_temp.uid``)."""
    return str(uuid.UUID(hashlib.md5(f'{org}:{kind}:{n}'.encode()).hexdigest()))


def ean13(n: int) -> str:
    """The barcode ``seed_scale_data.py`` gives product ``n`` (``pg_temp.ean13``)."""
    digits = '29' + str(n).zfill(10)
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits))
    return digits + str((10 - total % 10) % 10)


def fixtures(api: Api) -> dict:
    """Ids the reads and the screens are pointed at, chosen in the seeded organization."""
    org = api.get('/api/v1/organizations/my')['id']
    products = api.get('/api/v1/items/product-templates/count')
    count = products['count'] if isinstance(products, dict) else int(products)

    def location(code):
        answer = api.get(f'/api/v1/labels/scan/{quote(code)}')
        return answer['location']['id']

    product_n = max(1, count // 3)
    template = api.get(f'/api/v1/labels/scan/{ean13(product_n)}')['stock_summary']['template']
    # From a shelf's own list: the product list itself may be one of the
    # paths that fail at the size being measured.
    shelf = location('A05-002-3')
    record = _items_of(api.get(f'/api/v1/locations/{shelf}/items?limit=1&offset=0'))[0]
    po = api.get('/api/v1/purchase-orders?status=CONFIRMED&limit=1')
    po = (po['items'] if isinstance(po, dict) else po)[0]
    docs = api.get('/api/v1/warehouse/documents?type=OUT&status=COMPLETED&limit=1')
    doc = (docs['items'] if isinstance(docs, dict) else docs)[0]
    return {
        'org': org,
        'products': count,
        'shelf': shelf,
        'shelf_code': 'A05-002-3',
        'rack': location('A05-002'),
        'zone': location('A05'),
        'warehouse': location('WH-A'),
        'barcode': ean13(product_n),
        'template': template['id'],
        'sku': template['sku'],
        'record': record['id'],
        'category': seeded_uuid(org, 'cat', 7),
        'po': po['id'],
        'document': doc['id'],
        'document_number': doc['number'],
    }


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


def reads(f: dict) -> list[tuple[str, str, str]]:
    """``(name, class, path)`` of every read measured on its own."""
    today = date.today()
    past = (today - timedelta(days=90)).isoformat()
    items = '/api/v1/items?exclude_module_contexts=true&only_expired=false&limit=50'
    # The deepest page the product list offers: it counts ten thousand
    # records (LIST_COUNT_CAP) and its page jump stops there. The middle of
    # three hundred thousand records was a page no screen sends any more;
    # beyond the counted pages a reader searches or filters.
    deep = min(max(0, f['products'] * 3 // 2 // 50 * 50), 10_000 - 50)
    out = [
        ('items: first page', 'list', f'{items}&offset=0&sort_by=created_at&sort_order=desc'),
        ('items: search, common word', 'list', f'{items}&offset=0&search=bolt'),
        ('items: search, one barcode', 'lookup', f'{items}&offset=0&search={f["barcode"]}'),
        ('items: filter by category', 'list', f'{items}&offset=0&category_id={f["category"]}'),
        ('items: filter by shelf', 'list', f'{items}&offset=0&location_id={f["shelf"]}'),
        ('items: sort by name', 'list', f'{items}&offset=0&sort_by=name&sort_order=asc'),
        ('items: deep page (last counted)', 'list', f'{items}&offset={deep}&sort_by=created_at&sort_order=desc'),
        ('items: expiring in 30 days', 'list', f'{items}&offset=0&expiring_days=30'),
        ('items: low stock', 'list', f'{items}&offset=0&only_low_stock=true'),
        ('items: aggregates', 'report', '/api/v1/items/aggregates?exclude_module_contexts=true&only_expired=false'),
        ('scan: product barcode', 'lookup', f'/api/v1/labels/scan/{f["barcode"]}'),
        ('scan: shelf label', 'lookup', f'/api/v1/labels/scan/{f["shelf_code"]}'),
        ('product lookup by barcode', 'lookup', f'/api/v1/items/product-templates/lookup?barcode={f["barcode"]}'),
        ('product card: stock', 'lookup', f'/api/v1/items/product-templates/{f["template"]}/stock'),
        ('record card', 'lookup', f'/api/v1/items/{f["record"]}'),
        ('shelf: its records', 'list', f'/api/v1/locations/{f["shelf"]}/items?limit=50&offset=0'),
        ('shelf: its stock', 'list', f'/api/v1/stock-quants?location_id={f["shelf"]}&limit=50&offset=0'),
        ('zone: its stock', 'list', f'/api/v1/stock-quants?location_id={f["zone"]}&limit=50&offset=0'),
        ('stock: first page', 'list', '/api/v1/stock-quants?limit=50&offset=0'),
        ('batches: first page', 'list', '/api/v1/stock-lots?limit=50&offset=0'),
        ('location tree', 'list', '/api/v1/locations/tree?exclude_module_contexts=true'),
        ('locations: first page', 'list', '/api/v1/locations?limit=200&offset=0'),
        ('occupancy heat map', 'report', '/api/v1/warehouse/putaway/occupancy'),
        ('occupancy of a zone', 'report', f'/api/v1/warehouse/putaway/occupancy/{f["zone"]}'),
        ('To do', 'list', f'/api/v1/warehouse/todo?date_to={today.isoformat()}&limit=100&work_limit=100&view=all'),
        ('documents: first page', 'list', '/api/v1/warehouse/documents?limit=50&offset=0'),
        ('documents: search by number', 'lookup', f'/api/v1/warehouse/documents?limit=50&offset=0&search={quote(f["document_number"])}'),
        ('documents: completed dispatches', 'list', '/api/v1/warehouse/documents?type=OUT&status=COMPLETED&limit=50&offset=0'),
        ('document card', 'lookup', f'/api/v1/warehouse/documents/{f["document"]}'),
        ('purchase orders: first page', 'list', '/api/v1/purchase-orders?limit=50&offset=0'),
        ('journal: first page', 'list', '/api/v1/stock-moves?limit=50'),
        ('journal: one product', 'list', f'/api/v1/stock-moves?product_template_id={f["template"]}&limit=50'),
        ('journal: one shelf', 'list', f'/api/v1/stock-moves?location_id={f["shelf"]}&limit=50'),
        ('journal: last 30 days', 'list', f'/api/v1/stock-moves?since={(today - timedelta(days=30)).isoformat()}&limit=50'),
        ('stock as of 90 days ago', 'report', f'/api/v1/stock-as-of?as_of={past}'),
        ('stock as of 90 days ago, one zone', 'report', f'/api/v1/stock-as-of?as_of={past}&location_id={f["zone"]}'),
        ('valuation today (stock as of today)', 'report', f'/api/v1/stock-as-of?as_of={today.isoformat()}'),
        ('equipment valuation', 'report', '/api/v1/equipment/valuation'),
    ]
    for report in (
        'overview', 'by-category', 'by-location', 'expiry-forecast', 'low-stock',
        'consumption', 'cost-analysis', 'rotation-analysis', 'smart-alerts',
        'purchase-patterns', 'expense-forecast', 'activity', 'reconciliation',
    ):
        out.append((f'stats: {report}', 'report', f'/api/v1/stats/{report}'))
    # The product picker of receive and issue, a keystroke at a time.
    for typed in ('h', 'he', 'hex', 'hex ', 'hex b', 'hex bo', 'hex bol', 'hex bolt'):
        out.append((f'picker: "{typed}"', 'lookup', f'/api/v1/warehouse/product-search?q={quote(typed)}&limit=10'))
    out.append(('picker in stock: "hex bolt"', 'lookup', '/api/v1/warehouse/product-search?q=hex%20bolt&limit=10&stock=true'))
    out.append(('picker: by SKU', 'lookup', f'/api/v1/warehouse/product-search?q={f["sku"]}&limit=10'))
    return out


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


def _items_of(answer):
    return answer['items'] if isinstance(answer, dict) and 'items' in answer else answer


def _write(results, name, cls, api, method, path, payload=None, **kw):
    status, data, ms, size = api.call(method, path, payload, **kw)
    results[name] = {'class': cls, 'ms': round(ms, 1), 'status': status, 'bytes': size}
    if status >= 400:
        results[name]['error'] = str(data)[:400]
    print(f'  {name:<44} {status}  {ms:9.1f} ms  {results[name].get("error", "")[:160]}', flush=True)
    return status, data


def writes(api: Api, f: dict, import_rows: int) -> dict:
    """The write paths, once each, in an order that leaves the stock as it found it."""
    results: dict = {}
    # 200 products for the order — ones with no expiry date, which a receipt
    # of a product taken by earliest expiry would ask for line by line.
    # They come from the shelves' own lists rather than the product list,
    # which may be one of the paths that fail at the size being measured.
    templates = []
    for code in [f'A01-{rack:03d}-{level}' for rack in range(1, 4) for level in range(1, 9)]:
        shelf = api.get(f'/api/v1/labels/scan/{code}')['location']['id']
        templates += [r['template_id'] for r in _items_of(api.get(f'/api/v1/locations/{shelf}/items?limit=50&offset=0'))
                      if r.get('template_id') and not r.get('expiry_date')]
        if len(set(templates)) >= 200:
            break
    templates = list(dict.fromkeys(templates))[:200]

    status, po = _write(
        results, 'purchase order: create, 200 lines', 'write', api, 'POST', '/api/v1/purchase-orders',
        {
            'partner_id': seeded_uuid(f['org'], 'sup', 1),
            'lines': [{'product_template_id': t, 'quantity_ordered': 5, 'unit_price': 2.5} for t in templates],
        },
    )
    if status < 300:
        _write(results, 'purchase order: confirm', 'write', api, 'POST', f'/api/v1/purchase-orders/{po["id"]}/confirm')
        status, receipt = _write(
            results, 'receipt from the order, 200 lines', 'write', api, 'POST',
            f'/api/v1/purchase-orders/{po["id"]}/create-receipt', {'target_location_id': f['shelf']},
        )
        if status < 300:
            doc_id = receipt.get('id') or receipt.get('document_id')
            _write(results, 'receipt: confirm', 'write', api, 'PATCH', f'/api/v1/warehouse/documents/{doc_id}/confirm')
            _write(
                results, 'receipt: post (complete), 200 lines', 'write', api, 'PATCH',
                f'/api/v1/warehouse/documents/{doc_id}/complete', {'complete_as_planned': True},
            )
            _write(results, 'receipt: undo, 200 lines', 'write', api, 'POST', f'/api/v1/warehouse/documents/{doc_id}/undo')

    # Five dispatches of eight lines each from one zone, picked together:
    # each line names a record standing on a shelf of the zone, one with no
    # expiry date (an expired batch is not for sale and would not reserve).
    lines = []
    for code in [f'A05-00{rack}-{level}' for rack in (1, 2, 3) for level in range(1, 9)]:
        shelf = api.get(f'/api/v1/labels/scan/{code}')['location']['id']
        lines += [r for r in _items_of(api.get(f'/api/v1/locations/{shelf}/items?limit=50&offset=0'))
                  if float(r.get('quantity') or 0) >= 2 and r.get('template_id') and not r.get('expiry_date')]
        if len(lines) >= 40:
            break
    lines = lines[:40]
    dispatch_ids = []
    for n in range(5):
        chunk = lines[n * 8:(n + 1) * 8]
        if not chunk:
            break
        status, doc = _write(
            results, f'dispatch {n + 1}: create, {len(chunk)} lines', 'write', api, 'POST', '/api/v1/warehouse/documents',
            {
                'type': 'OUT',
                'partner_id': seeded_uuid(f['org'], 'cus', 1 + n),
                'source_location_id': f['zone'],
                'lines': [{'item_id': r['id'], 'product_template_id': r['template_id'], 'expected_quantity': 1} for r in chunk],
            },
        )
        if status < 300:
            status, _ = _write(results, f'dispatch {n + 1}: confirm', 'write', api, 'PATCH', f'/api/v1/warehouse/documents/{doc["id"]}/confirm')
            if status < 300:
                dispatch_ids.append(doc['id'])
    if dispatch_ids:
        status, session = _write(
            results, f'picking: start {len(dispatch_ids)} dispatches together', 'write', api, 'POST',
            '/api/v1/warehouse/picking/start', {'document_ids': dispatch_ids},
        )
        if status < 300:
            sid = session.get('id') or session.get('session_id')
            _write(results, 'picking: the pick list', 'lookup', api, 'GET', f'/api/v1/warehouse/documents/{dispatch_ids[0]}/picking')
            _write(results, 'picking: cancel', 'write', api, 'POST', f'/api/v1/warehouse/documents/{dispatch_ids[0]}/picking/{sid}/cancel')
    for n, doc_id in enumerate(dispatch_ids):
        _write(results, f'dispatch {n + 1}: cancel', 'write', api, 'PATCH', f'/api/v1/warehouse/documents/{doc_id}/cancel')

    # A stock take of one shelf: every record counted as it stands, closed.
    # One left open by an earlier run would refuse the new one.
    for old in _items_of(api.get('/api/v1/stock-takes?limit=100')):
        if old['location_id'] == f['shelf'] and old['status'] in ('draft', 'in_progress'):
            api.call('PATCH', f'/api/v1/stock-takes/{old["id"]}/status', {'status': 'cancelled'})
    status, take = _write(
        results, 'stock take of a shelf: create', 'write', api, 'POST', '/api/v1/stock-takes',
        {'name': f'Scale shelf count {datetime.now(UTC):%H%M%S}', 'location_id': f['shelf']},
    )
    if status >= 400:
        # Refused for the measured shelf (a finding of its own); the timing
        # comes from the first shelf of the tree.
        first = api.get('/api/v1/labels/scan/A01-001-1')['location']['id']
        status, take = _write(
            results, 'stock take of the first shelf: create', 'write', api, 'POST', '/api/v1/stock-takes',
            {'name': f'Scale shelf count {datetime.now(UTC):%H%M%S}', 'location_id': first},
        )
    if status < 300:
        counted = _items_of(api.get(f'/api/v1/stock-takes/{take["id"]}/items'))
        _write(
            results, f'stock take: count {len(counted)} records', 'write', api, 'PATCH',
            f'/api/v1/stock-takes/{take["id"]}/items/bulk-count',
            [{'item_id': c['id'], 'counted_quantity': c['system_quantity']} for c in counted],
        )
        _write(results, 'stock take: complete', 'write', api, 'POST', f'/api/v1/stock-takes/{take["id"]}/complete', {'apply_adjustments': True})

    # The spreadsheet export, of one zone and of everything.
    _write(results, 'export: one zone (xlsx)', 'report', api, 'GET', f'/api/v1/items/export/xlsx?location_id={f["zone"]}')
    _write(results, 'export: every record (xlsx)', 'bulk', api, 'GET', '/api/v1/items/export/xlsx')

    # An import of new records into one shelf, in files of at most
    # MAX_IMPORT_ROWS (backend/app/core/upload_validation.py) — the most one
    # file may hold, so a sheet of 100 000 rows is ten uploads.
    per_file = 10_000
    files = -(-import_rows // per_file)
    total_ms = 0.0
    for k in range(files):
        rows = min(per_file, import_rows - k * per_file)
        sheet = io.StringIO()
        writer = csv.writer(sheet)
        writer.writerow(['Name', 'Quantity', 'Location', 'Brand'])
        for n in range(rows):
            writer.writerow([f'Imported part {k:02d}-{n:05d}', 1 + n % 9, 'Shelf A01-001-1', 'Importco'])
        boundary = uuid.uuid4().hex
        mapping = {'name': 'Name', 'quantity': 'Quantity', 'location': 'Location', 'brand': 'Brand'}
        body = b''.join([
            f'--{boundary}\r\nContent-Disposition: form-data; name="mapping_json"\r\n\r\n{json.dumps(mapping)}\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="create_missing_locations"\r\n\r\nfalse\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="create_missing_categories"\r\n\r\nfalse\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="import.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode(),
            sheet.getvalue().encode(),
            f'\r\n--{boundary}--\r\n'.encode(),
        ])
        status, _ = _write(
            results, f'import: file {k + 1} of {files}, {rows:,} rows (csv)', 'bulk', api, 'POST',
            '/api/v1/items/import', raw=body, content_type=f'multipart/form-data; boundary={boundary}',
        )
        total_ms += results[f'import: file {k + 1} of {files}, {rows:,} rows (csv)']['ms']
        if status >= 400:
            break
    results[f'import: {import_rows:,} rows in all'] = {'class': 'bulk', 'ms': round(total_ms, 1), 'status': status, 'bytes': 0}
    return results


# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #


def screens(f: dict) -> list[dict]:
    """The daily screens, as the phone opens them."""
    return [
        {'name': 'launcher', 'path': '/'},
        {'name': 'products', 'path': '/inventory/items'},
        {'name': 'stock', 'path': '/inventory/stock'},
        {'name': 'batches', 'path': '/inventory/lots'},
        {'name': 'location tree', 'path': '/inventory/locations'},
        {'name': 'a shelf', 'path': f'/inventory/locations/{f["shelf"]}'},
        {'name': 'a zone', 'path': f'/inventory/locations/zone/{f["zone"]}'},
        {'name': 'occupancy', 'path': '/warehouse/occupancy'},
        {'name': 'todo', 'path': '/warehouse/todo'},
        {'name': 'board', 'path': '/warehouse/board'},
        {'name': 'receive', 'path': '/warehouse/receive'},
        {'name': 'issue', 'path': '/warehouse/issue'},
        {'name': 'move', 'path': '/warehouse/move'},
        {'name': 'history', 'path': '/warehouse/history'},
        {'name': 'register', 'path': '/warehouse/register'},
        {'name': 'a document', 'path': f'/warehouse/documents/{f["document"]}'},
        {'name': 'journal', 'path': '/inventory/moves'},
        {'name': 'stock as of', 'path': '/inventory/stock/as-of'},
        {'name': 'statistics', 'path': '/inventory/stats'},
        {'name': 'analytics', 'path': '/inventory/stats/analytics'},
        {'name': 'reconciliation', 'path': '/inventory/stats/reconciliation'},
        {'name': 'stock takes', 'path': '/inventory/stock-takes'},
        {'name': 'purchase orders', 'path': '/purchase-orders'},
        {'name': 'a purchase order', 'path': f'/purchase-orders/{f["po"]}'},
    ]


def phone_budget(name: str) -> int:
    budget = json.loads((FRONTEND / 'scripts' / 'phone-budget.json').read_text())
    key = PHONE_BUDGET_SCREENS.get(name)
    return budget['screens'][key]['budget']['loadMs'] if key else PHONE_DEFAULT_MS


def browser(api_base: str, f: dict, runs: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        screens_file, out = Path(tmp) / 'screens.json', Path(tmp) / 'browser.json'
        screens_file.write_text(json.dumps(screens(f)))
        env = {**os.environ, 'SCALE_API': api_base, 'SCALE_SCREENS': str(screens_file),
               'SCALE_OUT': str(out), 'SCALE_RUNS': str(runs)}
        subprocess.run(['node', 'scripts/measure-scale-screens.mjs'], cwd=FRONTEND, env=env, check=True)
        return json.loads(out.read_text())


def classify(path: str) -> str:
    report = ('/stats/', '/stock-as-of', '/occupancy', '/aggregates', '/valuation', '/export/')
    return 'report' if any(p in path for p in report) else 'list'


# --------------------------------------------------------------------------- #
# The run, and the report
# --------------------------------------------------------------------------- #


def machine() -> dict:
    """What a reader needs to compare a run with their own: cores and memory.

    The processor model, the kernel build and the interpreter describe one
    machine rather than a size, so a published result leaves them out.
    """
    info: dict = {'cores': os.cpu_count()}
    try:
        mem = Path('/proc/meminfo').read_text().splitlines()[0].split()[1]
        info['memory_gib'] = round(int(mem) / 1024 / 1024, 1)
    except (OSError, IndexError):
        pass
    return info


def load() -> list[float]:
    return [round(x, 1) for x in os.getloadavg()]


def time_screen_requests(api: Api, screens: dict, runs: int) -> dict:
    """Server time of the GET requests the screens sent, each request shape once."""
    print('Server time of the screens\' requests:', flush=True)
    seen: dict[str, dict] = {}
    for name, screen in screens.items():
        screen['budgetMs'] = phone_budget(name)
        for request in screen['api']:
            path = request['path']
            if request['method'] != 'GET' or path.startswith(SHELL_PATHS) or request['status'] != 200:
                continue
            # A screen that pages through a list sends the same request
            # with another offset each time; one of them is timed.
            shape = re.sub(r'offset=\d+', 'offset=N', path)
            if shape not in seen:
                seen[shape] = {'class': classify(path), 'path': path, **time_get(api, path, runs)}
            request['server'] = {k: seen[shape].get(k) for k in ('p50', 'p95')}
    return seen


def run(args) -> None:
    api = Api(args.api, args.email, args.password, args.pace)
    started = datetime.now(UTC)
    result = {
        'tier': args.tier,
        'started': started.isoformat(),
        'machine': machine(),
        'load_before': load(),
        'runs': args.runs,
    }
    # A half skipped now keeps what an earlier run wrote into the same file:
    # the reads and writes can be measured on the server's own host and the
    # screens from a machine with a browser, into one results file.
    out = Path(args.out)
    earlier = json.loads(out.read_text()) if out.exists() else {}
    for key, skipped in (('reads', args.skip_reads), ('screens', args.skip_browser),
                         ('screen_requests', args.skip_browser), ('writes', args.skip_writes)):
        if skipped and key in earlier:
            result[key] = earlier[key]
    # Each half names the machine it ran on: the server times belong to the
    # host, the phone's to the machine with the browser.
    if args.skip_reads and args.skip_writes:
        result['machine'], result['runs'] = earlier.get('machine', result['machine']), earlier.get('runs', args.runs)
    if not args.skip_browser:
        result['browser_machine'] = machine()
    elif 'browser_machine' in earlier:
        result['browser_machine'] = earlier['browser_machine']
    f = fixtures(api)
    result['fixtures'] = f
    print(f'Tier {args.tier}: {f["products"]:,} products; load {result["load_before"]}', flush=True)

    print('Reads:', flush=True)
    if not args.skip_reads:
        result['reads'] = {}
    for name, cls, path in [] if args.skip_reads else reads(f):
        timed = time_get(api, path, args.runs)
        result['reads'][name] = {'class': cls, 'path': path, **timed}
        flag = '' if timed.get('error') else ('  OVER' if timed['p95'] > BUDGET_MS[cls] else '')
        shown = f'status {timed["status"]}' if timed.get('error') else f'p50 {timed["p50"]:8.1f}  p95 {timed["p95"]:8.1f} ms'
        print(f'  {name:<44} {shown}  {timed["bytes"]:>10,} B{flag}', flush=True)
    result['load_after_reads'] = load()

    if not args.skip_browser:
        print('Screens on the phone:', flush=True)
        result['screens'] = browser(args.api, f, args.browser_runs)
        result['screen_requests'] = time_screen_requests(api, result['screens'], args.runs)
    result['load_after_screens'] = load()

    if not args.skip_writes:
        print('Writes:', flush=True)
        result['writes'] = writes(api, f, args.import_rows)
    result['finished'] = datetime.now(UTC).isoformat()
    result['load_after'] = load()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(f'Written to {args.out}')


def retime(args) -> None:
    """Time the screens' requests of a results file again, from this host."""
    out = Path(args.retime)
    result = json.loads(out.read_text())
    result['screen_requests'] = time_screen_requests(Api(args.api, args.email, args.password, args.pace), result['screens'], args.runs)
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(f'Written to {args.retime}')


def over(entry: dict) -> bool:
    if entry.get('error'):
        return False
    budget = BUDGET_MS.get(entry['class'])
    value = entry.get('p95', entry.get('ms'))
    return budget is not None and value is not None and value > budget


def report(paths: list[str]) -> None:
    """Markdown tables of one or more results files, tier by tier, side by side."""
    tiers = [json.loads(Path(p).read_text()) for p in paths]
    names = [t['tier'] for t in tiers]
    head = '| Path | Class | ' + ' | '.join(f'{n} p50 / p95 ms' for n in names) + ' |'
    rule = '|' + '---|' * (2 + len(names))
    print('### Reads (server time)\n')
    print(head)
    print(rule)
    for name, first in tiers[0]['reads'].items():
        cells = []
        for t in tiers:
            e = t['reads'].get(name, {})
            if not e or e.get('error'):
                cells.append(f'status {e.get("status", "—")}')
            else:
                mark = ' **over**' if over(e) else ''
                cells.append(f'{e["p50"]:,.0f} / {e["p95"]:,.0f}{mark}')
        print(f'| {name} | {first["class"]} | ' + ' | '.join(cells) + ' |')
    if all('writes' in t for t in tiers):
        print('\n### Writes and bulk work (one run)\n')
        print('| Path | Class | ' + ' | '.join(f'{n} ms' for n in names) + ' |')
        print(rule)
        for name, first in tiers[0]['writes'].items():
            cells = []
            for t in tiers:
                e = t['writes'].get(name, {})
                if not e:
                    cells.append('—')
                elif e.get('error'):
                    cells.append(f'status {e["status"]}')
                else:
                    cells.append(f'{e["ms"]:,.0f}' + (' **over**' if over(e) else ''))
            print(f'| {name} | {first["class"]} | ' + ' | '.join(cells) + ' |')
    if all('screens' in t for t in tiers):
        print('\n### Screens on the phone (usable, median) and what they download\n')
        print('| Screen | Budget ms | ' + ' | '.join(f'{n} usable ms · API KiB · slowest request p95 ms' for n in names) + ' |')
        print('|---|---|' + '---|' * len(names))
        for name, first in tiers[0]['screens'].items():
            cells = []
            for t in tiers:
                s = t['screens'].get(name)
                if not s:
                    cells.append('—')
                    continue
                slowest = max((r.get('server', {}).get('p95') or 0 for r in s['api']), default=0)
                usable = s['usableMs']
                mark = ' **over**' if usable is None or usable > s['budgetMs'] else ''
                shown = f'{usable:,}' if usable is not None else 'not in 120 s'
                # A 500 is the application's error: that part of the screen
                # has no data to act on. A 502 is the request the proxy lost
                # when the worker answering it died, which the browser retries.
                for status in (500, 502):
                    failed = sum(1 for r in s['api'] if r['status'] == status)
                    if failed:
                        mark += f' **{failed}× {status}**'
                cells.append(f'{shown}{mark} · {s["apiKiB"]:,.0f} · {slowest:,.0f}')
            print(f'| {name} | {first.get("budgetMs", PHONE_DEFAULT_MS):,} | ' + ' | '.join(cells) + ' |')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    parser.add_argument('--email', default=os.environ.get('DEV_ADMIN_EMAIL', 'admin@example.com'))
    parser.add_argument('--password', default=os.environ.get('DEV_ADMIN_PASSWORD', 'Admin123'))
    parser.add_argument('--tier', default='unnamed')
    parser.add_argument('--out', default='load_tests/scale/results/unnamed.json')
    parser.add_argument('--runs', type=int, default=20, help='timed runs of each read')
    parser.add_argument('--browser-runs', type=int, default=3, help='phone runs of each screen')
    parser.add_argument('--import-rows', type=int, default=100_000)
    parser.add_argument('--pace', type=float, default=0.0, help='seconds between two requests (0.35 keeps under 200 a minute)')
    parser.add_argument('--skip-reads', action='store_true')
    parser.add_argument('--skip-browser', action='store_true')
    parser.add_argument('--skip-writes', action='store_true')
    parser.add_argument('--report', nargs='+', metavar='RESULTS', help='print the tables of results files')
    parser.add_argument('--retime', metavar='RESULTS', help="time the screens' requests of a results file from this host")
    args = parser.parse_args()
    if args.report:
        report(args.report)
        return
    if args.retime:
        retime(args)
        return
    run(args)


if __name__ == '__main__':
    sys.exit(main())
