"""
Seeds one organization at warehouse scale, for measuring Inventari at size.

The demo organization holds about a hundred products and the load-test seeder
writes three hundred bare records per organization; neither says anything about
a warehouse of hundreds of thousands of products, a location tree with tens of
thousands of shelves and a year of movements behind every one of them. This
script builds that organization, in the shape the posting rules produce:

- product cards with a barcode (GS1 restricted-circulation EAN-13, so no real
  product is named and no outside catalogue is ever asked), a SKU and a unit;
- categories whose custom fields the records fill in;
- one warehouse four levels deep — zones, racks, shelves (``--shelves``,
  2 000 by default, however large the catalogue) — plus a receiving zone of
  dock lanes;
- about three records per product spread across the shelves, a third of the
  products batch-tracked with an expiry date on most batches, every group of
  stock with its anchor;
- a movement journal of about ten movements per product covering the
  history window: each record received (some through a dock lane and put
  away from there), then dispatched in parts, every movement named by the
  completed document that moved it and every receipt and dispatch with its
  cost layer, the receipt layers drained first-in-first-out per product;
- suppliers, customers and purchase orders in proportion, and open work —
  purchase orders and receipts expected, dispatches in draft — so the To do
  screens have something to show.

The rows are written by ``INSERT ... SELECT`` over ``generate_series`` inside
the database, not one ORM row at a time: a million products seed in minutes.
Every value is a hash of the row's number and ``--seed``, so two runs with the
same arguments write the same organization. At the end the stock
reconciliation is run over it, and a drift is a failure.

Usage (the account must exist; its organization is onboarded as a warehouse
first if it has not been):

    docker compose exec backend uv run python seed_scale_data.py --products 100000
    make seed-scale PRODUCTS=100000

The organization must hold no stock yet: the seeder writes into an empty one
and refuses otherwise. ``load_tests/README.md`` ("Warehouse scale") describes
the measurement that runs on top of it.
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text

from app.core.module_registry import module_registry
from app.database import SessionLocal
from app.models.item import Item
from app.models.organization import Organization
from app.models.user import User

# Standalone seeders bypass app.main startup; see seed_load_test_data.py.
module_registry.discover_modules()

ADMIN_EMAIL = 'admin@example.com'

#: Receipts land in the past this many days back, dispatches between their
#: receipt and today — a year and a month of journal.
HISTORY_DAYS = 400

#: Lines per completed document, roughly: a delivery note, a dispatch, the
#: put-away of a day's dock lane.
RECEIPT_LINES = 25
DISPATCH_LINES = 10

NAME_ADJECTIVES = [
    'Stainless',
    'Galvanised',
    'Brass',
    'Nylon',
    'Zinc-plated',
    'Heavy-duty',
    'Compact',
    'Industrial',
    'Flexible',
    'Insulated',
    'Reinforced',
    'Coated',
    'Black',
    'White',
    'Red',
    'Blue',
    'Grey',
    'Green',
    'Yellow',
    'Transparent',
    'Anodised',
    'Hardened',
    'Waterproof',
    'Low-profile',
    'Self-locking',
    'Quick-release',
    'Precision',
    'Standard',
    'Economy',
    'Professional',
]
NAME_NOUNS = [
    'hex bolt',
    'wood screw',
    'lock nut',
    'flat washer',
    'angle bracket',
    'door hinge',
    'power cable',
    'connector',
    'fuse',
    'toggle switch',
    'relay',
    'ball bearing',
    'gasket',
    'garden hose',
    'ball valve',
    'pipe fitting',
    'air filter',
    'drive belt',
    'roller chain',
    'compression spring',
    'dowel pin',
    'blind rivet',
    'hose clamp',
    'wall anchor',
    'cup hook',
    'duct tape',
    'work glove',
    'dust mask',
    'shipping label',
    'carton box',
    'poly bag',
    'stretch film',
    'drill bit',
    'saw blade',
    'sanding disc',
    'battery',
    'lamp',
    'LED strip',
    'motion sensor',
    'power adapter',
    'cable tie',
    'junction box',
    'circuit breaker',
    'extension lead',
    'paint brush',
    'paint roller',
    'sealant',
    'adhesive',
    'lubricant',
    'padlock',
]
BRAND_HEADS = [
    'Al',
    'Bor',
    'Cen',
    'Dra',
    'El',
    'Fen',
    'Gal',
    'Hol',
    'Ist',
    'Jor',
    'Kel',
    'Lun',
    'Mar',
    'Nor',
    'Orv',
    'Pel',
    'Quor',
    'Ras',
    'Sel',
    'Tor',
    'Ul',
    'Ves',
    'Wen',
    'Zar',
]
BRAND_TAILS = [
    'ton',
    'vex',
    'mar',
    'dell',
    'brook',
    'stad',
    'wick',
    'more',
    'field',
    'gate',
    'tek',
    'line',
    'craft',
    'works',
    'forge',
    'ridge',
    'haven',
    'port',
    'well',
    'stone',
    'ford',
    'by',
    'mont',
    'dale',
    'holt',
]
CATEGORY_NAMES = [
    'Fasteners',
    'Hand tools',
    'Power tools',
    'Electrical',
    'Lighting',
    'Plumbing',
    'Heating',
    'Ventilation',
    'Safety equipment',
    'Workwear',
    'Packaging',
    'Adhesives',
    'Paints',
    'Abrasives',
    'Cutting tools',
    'Bearings',
    'Seals',
    'Hydraulics',
    'Pneumatics',
    'Cables',
    'Connectors',
    'Batteries',
    'Sensors',
    'Locks',
    'Hinges',
    'Shelving',
    'Storage boxes',
    'Cleaning',
    'Lubricants',
    'Garden',
    'Ironmongery',
    'Timber',
    'Sheet metal',
    'Pipes',
    'Valves',
    'Filters',
    'Belts',
    'Chains',
    'Springs',
    'Labels',
]
#: The custom fields the categories declare: three of these each, filled in
#: on every record of the category.
CUSTOM_FIELDS = [
    {
        'key': 'material',
        'type': 'select',
        'label': 'Material',
        'options': [
            'Steel',
            'Stainless steel',
            'Brass',
            'Aluminium',
            'Nylon',
            'Rubber',
            'Copper',
        ],
    },
    {'key': 'pack_size', 'type': 'number', 'label': 'Pack size'},
    {'key': 'grade', 'type': 'select', 'label': 'Grade', 'options': ['A', 'B', 'C']},
    {
        'key': 'colour',
        'type': 'select',
        'label': 'Colour',
        'options': ['Black', 'White', 'Red', 'Blue', 'Grey', 'Yellow'],
    },
    {'key': 'voltage', 'type': 'number', 'label': 'Voltage (V)'},
    {'key': 'length_mm', 'type': 'number', 'label': 'Length (mm)'},
    {'key': 'standard', 'type': 'text', 'label': 'Standard'},
    {'key': 'supplier_ref', 'type': 'text', 'label': 'Supplier reference'},
]


def _say(message: str) -> None:
    print(message, flush=True)


class _Steps:
    """Runs the seed's statements one step at a time and says how long each took."""

    def __init__(self, conn):
        self.conn = conn
        self.started = time.monotonic()
        self.timings: dict[str, float] = {}

    def run(self, label: str, *statements: tuple[str, dict] | str) -> int:
        began = time.monotonic()
        rows = 0
        for statement in statements:
            sql, params = statement if isinstance(statement, tuple) else (statement, {})
            result = self.conn.execute(text(sql), params)
            rows += max(result.rowcount or 0, 0)
        took = time.monotonic() - began
        self.timings[label] = round(took, 1)
        _say(f'  {label:<34} {rows:>11,} rows  {took:7.1f} s')
        return rows


#: Shelves of the one warehouse, whatever the size of the catalogue. A small
#: or medium business has hundreds to a few thousand places to put things,
#: and a shelf of small parts holds hundreds of products: the catalogue grows,
#: the building does not.
DEFAULT_SHELVES = 2_000


def _sizes(products: int, shelves: int = DEFAULT_SHELVES) -> dict[str, int]:
    """Every count the seed derives from the number of products and shelves."""
    warehouses = 1
    zones = 10
    levels = 8
    racks = math.ceil(shelves / (warehouses * zones * levels))
    records = products * 3
    return {
        'products': products,
        'warehouses': warehouses,
        'zones': zones,
        'racks': racks,
        'levels': levels,
        'shelves': warehouses * zones * racks * levels,
        'suppliers': 30 + products // 2_000,
        'customers': 100 + products // 250,
        'categories': len(CATEGORY_NAMES),
        'receipt_docs_per_day': max(
            1, math.ceil(records / (HISTORY_DAYS * warehouses * RECEIPT_LINES))
        ),
        # About two dispatches a record (records x 2.2 / days / lines).
        'dispatch_docs_per_day': max(
            1, math.ceil(records * 2.2 / (HISTORY_DAYS * warehouses * DISPATCH_LINES))
        ),
        'open_documents': 20 + products // 5_000,
    }


def _functions(seed: int, org_id: str) -> list[str]:
    """The session's helpers: a seeded hash, a fraction, a stable id, an EAN-13."""
    return [
        f"""
        CREATE FUNCTION pg_temp.h(n bigint, k int) RETURNS bigint
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$ SELECT hashint8extended(n, {int(seed)}::bigint * 1000 + k) & 9223372036854775807 $$
        """,
        """
        CREATE FUNCTION pg_temp.u(n bigint, k int) RETURNS float8
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$ SELECT pg_temp.h(n, k)::float8 / 9223372036854775807::float8 $$
        """,
        f"""
        CREATE FUNCTION pg_temp.uid(kind text, n bigint) RETURNS uuid
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$ SELECT md5('{org_id}:' || kind || ':' || n)::uuid $$
        """,
        # A GS1 restricted-circulation code (prefix 29): assigned in-house,
        # printed on no retail product, never looked up outside.
        """
        CREATE FUNCTION pg_temp.ean13(n bigint) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$
          SELECT d || ((10 - (
            SELECT sum(substr(d, p, 1)::int * CASE WHEN p % 2 = 0 THEN 3 ELSE 1 END)
            FROM generate_series(1, 12) p) % 10) % 10)::text
          FROM (SELECT '29' || lpad(n::text, 10, '0') AS d) s
        $$
        """,
    ]


def _custom_field_value_sql() -> str:
    """``pg_temp.fv(key, n)``: the value a record holds in a custom field."""
    cases = []
    for field in CUSTOM_FIELDS:
        key = field['key']
        if field['type'] == 'select':
            options = ', '.join(f"'{o}'" for o in field['options'])
            value = f'to_jsonb((ARRAY[{options}])[1 + pg_temp.h(n, 61) % {len(field["options"])}])'
        elif field['type'] == 'number':
            value = 'to_jsonb(1 + pg_temp.h(n, 62) % 500)'
        else:
            value = "to_jsonb(upper(substr(md5(n::text || key), 1, 3)) || '-' || (pg_temp.h(n, 63) % 9000 + 1000))"
        cases.append(f"WHEN '{key}' THEN {value}")
    return f"""
        CREATE FUNCTION pg_temp.fv(key text, n bigint) RETURNS jsonb
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$ SELECT CASE key {' '.join(cases)} END $$
    """


def _seed_statements(ctx: dict, size: dict) -> list[tuple[str, list]]:
    """The seed, as labelled groups of statements, in the order they run."""
    p = {
        'org': ctx['org'],
        'user': ctx['user'],
        'now': ctx['now'],
        'currency': ctx['currency'],
        'pcs': ctx['pcs'],
        'box': ctx['box'],
        'shelf_type': ctx['shelf_type'],
        'room_type': ctx['room_type'],
        'days': HISTORY_DAYS,
        'adjs': NAME_ADJECTIVES,
        'nouns': NAME_NOUNS,
        'brands': [h + t for h in BRAND_HEADS for t in BRAND_TAILS],
        'cat_names': CATEGORY_NAMES,
        # Three custom fields a category, filled in on every record of it.
        'cat_keys': [
            CUSTOM_FIELDS[(c + offset) % len(CUSTOM_FIELDS)]['key']
            for c in range(size['categories'])
            for offset in (0, 3, 5)
        ],
        **size,
    }
    groups: list[tuple[str, list]] = []

    def add(label: str, *sql: str) -> None:
        groups.append((label, [(s, p) for s in sql]))

    add(
        'partners',
        """
        CREATE TEMP TABLE scale_partners AS
        SELECT 'sup' AS kind, n, pg_temp.uid('sup', n) AS id, 'SUPPLIER' AS type,
               (:brands)[1 + pg_temp.h(n, 1) % cardinality(:brands)] || ' Supply ' || n AS name,
               'SUP-' || lpad(n::text, 5, '0') AS code
        FROM generate_series(1, :suppliers) n
        UNION ALL
        SELECT 'cus', n, pg_temp.uid('cus', n), 'CUSTOMER',
               (:brands)[1 + pg_temp.h(n, 2) % cardinality(:brands)] || ' Trading ' || n,
               'CUS-' || lpad(n::text, 6, '0')
        FROM generate_series(1, :customers) n
        """,
        """
        INSERT INTO partners (id, organization_id, name, code, type, is_consumer, email,
                              is_active, created_by, created_at, updated_at)
        SELECT id, CAST(:org AS uuid), name, code, type, false,
               lower(code) || '@partner.example.com', true, CAST(:user AS uuid),
               CAST(:now AS timestamptz) - interval '500 days',
               CAST(:now AS timestamptz) - interval '500 days'
        FROM scale_partners
        """,
    )
    add(
        'locations',
        """
        CREATE TEMP TABLE scale_shelves AS
        SELECT ((w * :zones + z) * :racks + k) * :levels + l AS idx, w AS wh,
               pg_temp.uid('shelf', ((w * 100 + z) * 10000 + k) * 10 + l) AS id,
               pg_temp.uid('rack', (w * 100 + z) * 10000 + k) AS rack_id,
               chr(65 + w) || lpad((z + 1)::text, 2, '0') || '-'
                 || lpad((k + 1)::text, 3, '0') || '-' || (l + 1) AS code
        FROM generate_series(0, :warehouses - 1) w,
             generate_series(0, :zones - 1) z,
             generate_series(0, :racks - 1) k,
             generate_series(0, :levels - 1) l
        """,
        'CREATE UNIQUE INDEX ON scale_shelves (idx)',
        """
        INSERT INTO storage_locations (id, organization_id, parent_id, storage_type_id, name,
                                       short_code, sequence, usage, behavior_mode,
                                       created_at, created_by)
        SELECT pg_temp.uid('wh', w), CAST(:org AS uuid), NULL, CAST(:room_type AS uuid),
               'Warehouse ' || chr(65 + w), 'WH-' || chr(65 + w), NULL::int, 'internal', 'STOCK',
               CAST(:now AS timestamptz) - interval '500 days', CAST(:user AS uuid)
        FROM generate_series(0, :warehouses - 1) w
        UNION ALL
        SELECT pg_temp.uid('zone', w * 100 + z), CAST(:org AS uuid), pg_temp.uid('wh', w), NULL,
               'Zone ' || chr(65 + w) || lpad((z + 1)::text, 2, '0'),
               chr(65 + w) || lpad((z + 1)::text, 2, '0'), NULL, 'internal', 'STOCK',
               CAST(:now AS timestamptz) - interval '500 days', CAST(:user AS uuid)
        FROM generate_series(0, :warehouses - 1) w, generate_series(0, :zones - 1) z
        UNION ALL
        SELECT pg_temp.uid('rack', (w * 100 + z) * 10000 + k), CAST(:org AS uuid),
               pg_temp.uid('zone', w * 100 + z), NULL,
               'Rack ' || chr(65 + w) || lpad((z + 1)::text, 2, '0') || '-' || lpad((k + 1)::text, 3, '0'),
               chr(65 + w) || lpad((z + 1)::text, 2, '0') || '-' || lpad((k + 1)::text, 3, '0'),
               NULL, 'internal', 'STOCK',
               CAST(:now AS timestamptz) - interval '500 days', CAST(:user AS uuid)
        FROM generate_series(0, :warehouses - 1) w, generate_series(0, :zones - 1) z,
             generate_series(0, :racks - 1) k
        UNION ALL
        SELECT id, CAST(:org AS uuid), rack_id, CAST(:shelf_type AS uuid), 'Shelf ' || code, code, idx::int,
               'internal', 'STOCK', CAST(:now AS timestamptz) - interval '500 days', CAST(:user AS uuid)
        FROM scale_shelves
        UNION ALL
        SELECT pg_temp.uid('dockzone', w), CAST(:org AS uuid), pg_temp.uid('wh', w), NULL,
               'Receiving ' || chr(65 + w), chr(65 + w) || '-RCV', NULL, 'internal', 'STOCK',
               CAST(:now AS timestamptz) - interval '500 days', CAST(:user AS uuid)
        FROM generate_series(0, :warehouses - 1) w
        UNION ALL
        SELECT pg_temp.uid('dock', w * 100 + d), CAST(:org AS uuid), pg_temp.uid('dockzone', w),
               CAST(:shelf_type AS uuid),
               'Dock ' || chr(65 + w) || '-' || lpad((d + 1)::text, 2, '0'),
               chr(65 + w) || '-RCV-' || lpad((d + 1)::text, 2, '0'), NULL, 'internal', 'STOCK',
               CAST(:now AS timestamptz) - interval '500 days', CAST(:user AS uuid)
        FROM generate_series(0, :warehouses - 1) w, generate_series(0, 9) d
        """,
    )
    add(
        'categories',
        """
        INSERT INTO categories (id, organization_id, name, code, sort_order, is_active,
                                field_definitions)
        SELECT pg_temp.uid('cat', c), CAST(:org AS uuid), (:cat_names)[c + 1],
               'scale_' || c, c, true,
               json_build_array(
                 pg_temp.field_def((:cat_keys)[c * 3 + 1]),
                 pg_temp.field_def((:cat_keys)[c * 3 + 2]),
                 pg_temp.field_def((:cat_keys)[c * 3 + 3]))
        FROM generate_series(0, :categories - 1) c
        """,
    )
    add(
        'products',
        """
        CREATE TEMP TABLE scale_products AS
        SELECT i, pg_temp.uid('pt', i) AS id,
               (:adjs)[1 + pg_temp.h(i, 1) % cardinality(:adjs)] || ' '
                 || (:nouns)[1 + pg_temp.h(i, 2) % cardinality(:nouns)] || ' '
                 || CASE pg_temp.h(i, 11) % 3
                      WHEN 0 THEN 'M' || (3 + pg_temp.h(i, 12) % 22) || 'x' || (10 + 5 * (pg_temp.h(i, 13) % 30))
                      WHEN 1 THEN (5 + pg_temp.h(i, 12) % 995) || ' mm'
                      ELSE upper(substr(md5(i::text), 1, 2)) || '-' || (100 + pg_temp.h(i, 13) % 9900)
                    END AS name,
               (:brands)[1 + pg_temp.h(i, 3) % cardinality(:brands)] AS brand,
               pg_temp.ean13(i) AS barcode,
               (pg_temp.h(i, 4) % :categories)::int AS cat,
               round((0.5 + pg_temp.u(i, 5) ^ 2 * 400)::numeric, 2) AS cost,
               pg_temp.u(i, 6) < 0.35 AS lot,
               pg_temp.u(i, 7) < 0.6 AS perish,
               (1 + pg_temp.h(i, 8) % 5)::int AS nrec,
               pg_temp.h(i, 9) % :shelves AS home,
               1 + pg_temp.h(i, 10) % 37 AS stride,
               CASE WHEN pg_temp.u(i, 14) < 0.85 THEN CAST(:pcs AS uuid) ELSE CAST(:box AS uuid) END AS uom
        FROM generate_series(1, :products) i
        """,
        """
        INSERT INTO product_templates (id, organization_id, name, brand, barcode, sku, uom_id,
                                       min_quantity, removal_strategy, created_at, updated_at)
        SELECT id, CAST(:org AS uuid), name, brand, barcode, 'SKU-' || lpad(i::text, 7, '0'), uom,
               CASE WHEN pg_temp.u(i, 15) < 0.2 THEN 5 + pg_temp.h(i, 16) % 46 END,
               CASE WHEN lot AND perish THEN 'FEFO' END,
               CAST(:now AS timestamptz) - interval '480 days',
               CAST(:now AS timestamptz) - interval '480 days'
        FROM scale_products
        """,
    )
    add(
        'records (staging)',
        """
        CREATE TEMP TABLE scale_records AS
        SELECT b.*,
               b.qty + (SELECT coalesce(sum(1 + pg_temp.h(b.rec * 8 + m, 27) % 30), 0)
                        FROM generate_series(0, b.k - 1) m)::numeric AS q0,
               CASE WHEN b.via_dock THEN pg_temp.uid('dock', b.wh * 100 + pg_temp.h(b.rec, 31) % 10)
                    ELSE b.shelf_id END AS landed_id,
               ((b.recv_ago * :warehouses + b.wh) * :receipt_docs_per_day
                 + pg_temp.h(b.rec, 30) % :receipt_docs_per_day) AS in_key,
               CASE WHEN b.via_dock
                    THEN (CAST(:now AS date) - (b.recv_at + (CAST(:now AS timestamptz) - b.recv_at)
                           * (0.5 / (b.k + 1)))::date) * :warehouses + b.wh END AS int_key,
               b.recv_at + (CAST(:now AS timestamptz) - b.recv_at) * (0.5 / (b.k + 1)) AS int_at,
               b.recv_at + (CAST(:now AS timestamptz) - b.recv_at) * (b.k::float8 / (b.k + 1)) AS last_at,
               CASE WHEN b.lot THEN 'L' || to_char(b.recv_at, 'YYMMDD') || '-' || (b.j + 1) END AS lot_name,
               CASE WHEN b.lot AND b.perish
                    THEN b.recv_at::date + (20 + pg_temp.h(b.rec, 29) % 480)::int END AS expiry
        FROM (
          SELECT r.rec, p.i, j, pg_temp.uid('rec', r.rec) AS id, p.id AS template_id,
                 p.name, p.brand, p.barcode, p.cat, p.uom, p.lot, p.perish,
                 s.idx AS shelf, s.id AS shelf_id, s.wh,
                 CASE WHEN pg_temp.u(r.rec, 20) < 0.08 THEN 0
                      ELSE 1 + floor(pg_temp.u(r.rec, 21) ^ 2 * 240) END::numeric AS qty,
                 CASE WHEN pg_temp.u(r.rec, 20) < 0.08 THEN 1 + pg_temp.h(r.rec, 22) % 4
                      ELSE pg_temp.h(r.rec, 22) % 5 END::int AS k,
                 (1 + pg_temp.h(r.rec, 23) % :days)::int AS recv_ago,
                 CAST(:now AS timestamptz)
                   - make_interval(days => (1 + pg_temp.h(r.rec, 23) % :days)::int,
                                   mins => (pg_temp.h(r.rec, 25) % 600)::int) AS recv_at,
                 pg_temp.u(r.rec, 24) < 0.12 AS via_dock,
                 round(p.cost * (0.9 + 0.2 * pg_temp.u(r.rec, 28))::numeric, 4) AS unit_cost,
                 CASE WHEN p.lot THEN pg_temp.uid('lot', r.rec) END AS lot_id
          FROM scale_products p
          CROSS JOIN LATERAL generate_series(0, p.nrec - 1) j
          CROSS JOIN LATERAL (SELECT p.i::bigint * 8 + j AS rec) r
          JOIN scale_shelves s ON s.idx = (p.home + j * p.stride) % :shelves
        ) b
        """,
        'CREATE UNIQUE INDEX ON scale_records (rec)',
        """
        CREATE TEMP TABLE scale_out AS
        SELECT r.rec, m, r.rec * 8 + m AS ok, r.id AS record_id, r.template_id, r.shelf_id, r.wh,
               r.name, r.brand, r.barcode, r.uom, r.unit_cost, r.lot_id, r.lot_name, r.expiry,
               (1 + pg_temp.h(r.rec * 8 + m, 27) % 30)::numeric AS qty, a.at,
               ((CAST(:now AS date) - a.at::date) * :warehouses + r.wh) * :dispatch_docs_per_day
                 + pg_temp.h(r.rec * 8 + m, 33) % :dispatch_docs_per_day AS out_key
        FROM scale_records r
        CROSS JOIN LATERAL generate_series(0, r.k - 1) m
        CROSS JOIN LATERAL (
          SELECT r.recv_at + (CAST(:now AS timestamptz) - r.recv_at) * ((m + 1)::float8 / (r.k + 1)) AS at
        ) a
        """,
    )
    add(
        'batches',
        """
        INSERT INTO stock_lots (id, organization_id, product_template_id, name, is_serial,
                                expiry_date, production_date, removal_strategy, status, created_at)
        SELECT lot_id, CAST(:org AS uuid), template_id, lot_name, false, expiry,
               recv_at::date - 10, CASE WHEN perish THEN 'FEFO' ELSE 'FIFO' END, 'active', recv_at
        FROM scale_records WHERE lot
        """,
    )
    add(
        'documents',
        # Completed receipts: one per warehouse, day and delivery slot; a
        # quarter of them against a purchase order.
        """
        CREATE TEMP TABLE scale_docs AS
        SELECT 'IN' AS type, in_key AS key, pg_temp.uid('din', in_key) AS id, min(wh) AS wh,
               min(recv_at) AS started, max(recv_at) AS finished,
               sum(round(q0 * unit_cost, 2)) AS net,
               pg_temp.uid('sup', 1 + pg_temp.h(in_key, 32) % :suppliers) AS partner_id,
               pg_temp.h(in_key, 34) % 4 = 0 AS with_po
        FROM scale_records GROUP BY in_key
        UNION ALL
        SELECT 'OUT', out_key, pg_temp.uid('dout', out_key), min(wh), min(at), max(at),
               sum(round(qty * round(unit_cost * 1.35, 2), 2)),
               pg_temp.uid('cus', 1 + pg_temp.h(out_key, 35) % :customers), false
        FROM scale_out GROUP BY out_key
        UNION ALL
        SELECT 'INT', int_key, pg_temp.uid('dint', int_key), min(wh), min(int_at), max(int_at),
               NULL, NULL, false
        FROM scale_records WHERE via_dock GROUP BY int_key
        """,
        """
        INSERT INTO documents (id, organization_id, type, number, status, partner_id,
                               partner_snapshot, source_location_id, target_location_id,
                               scheduled_date, external_reference, total_net, total_tax,
                               total_gross, currency, created_by, confirmed_by, completed_by,
                               created_at, updated_at, confirmed_at, completed_at)
        SELECT d.id, CAST(:org AS uuid), d.type,
               d.type || '/' || extract(year FROM d.finished)::int || '/'
                 || lpad(row_number() OVER (PARTITION BY d.type, extract(year FROM d.finished)
                                            ORDER BY d.finished, d.key)::text, 6, '0'),
               'COMPLETED', d.partner_id,
               CASE WHEN sp.id IS NOT NULL THEN jsonb_build_object('name', sp.name, 'code', sp.code) END,
               CASE d.type WHEN 'OUT' THEN pg_temp.uid('wh', d.wh)
                           WHEN 'INT' THEN pg_temp.uid('dockzone', d.wh) END,
               CASE d.type WHEN 'IN' THEN pg_temp.uid('wh', d.wh)
                           WHEN 'INT' THEN pg_temp.uid('wh', d.wh) END,
               d.started::date,
               CASE WHEN d.type = 'IN' THEN 'DN-' || d.key END,
               d.net, round(d.net * 0.23, 2), d.net + round(d.net * 0.23, 2),
               :currency, CAST(:user AS uuid), CAST(:user AS uuid), CAST(:user AS uuid),
               d.started - interval '2 hours', d.finished, d.started - interval '1 hour', d.finished
        FROM scale_docs d LEFT JOIN scale_partners sp ON sp.id = d.partner_id
        """,
        """
        INSERT INTO purchase_orders (id, organization_id, number, status, partner_id,
                                     scheduled_date, currency, created_by, confirmed_by,
                                     confirmed_at, created_at, updated_at)
        SELECT pg_temp.uid('po', key), CAST(:org AS uuid),
               'PO/' || extract(year FROM started - interval '7 days')::int || '/'
                 || lpad(row_number() OVER (PARTITION BY extract(year FROM started - interval '7 days')
                                            ORDER BY started, key)::text, 6, '0'),
               'COMPLETED', partner_id, started::date, :currency, CAST(:user AS uuid), CAST(:user AS uuid),
               started - interval '6 days', started - interval '7 days', finished
        FROM scale_docs WHERE type = 'IN' AND with_po
        """,
        """
        INSERT INTO purchase_order_lines (id, purchase_order_id, product_template_id, name,
                                          quantity_ordered, quantity_received, unit_price,
                                          uom_id, tax_rate, line_number)
        SELECT pg_temp.uid('pol', r.rec), pg_temp.uid('po', r.in_key), r.template_id, r.name,
               r.q0, r.q0, round(r.unit_cost, 2), r.uom, 23,
               row_number() OVER (PARTITION BY r.in_key ORDER BY r.rec)
        FROM scale_records r JOIN scale_docs d ON d.type = 'IN' AND d.key = r.in_key AND d.with_po
        """,
    )
    add(
        'anchors',
        # Every group that ever held stock keeps its anchor, the dock lanes a
        # receipt passed through included (docs/subsystems/STOCK.md).
        """
        INSERT INTO stock_anchors (id, organization_id, product_template_id, storage_location_id,
                                   created_at)
        SELECT md5(CAST(:org AS text) || ':anchor:' || template_id || ':' || location_id)::uuid,
               CAST(:org AS uuid), template_id, location_id, min(at)
        FROM (SELECT template_id, shelf_id AS location_id, recv_at AS at FROM scale_records
              UNION ALL
              SELECT template_id, landed_id, recv_at FROM scale_records WHERE via_dock) g
        GROUP BY template_id, location_id
        """,
    )
    add(
        'records',
        """
        INSERT INTO items (id, organization_id, storage_location_id, category_id, name, brand,
                           uom_id, template_id, quantity, added_date, expiry_date, meta_data,
                           purchase_price, currency, is_deleted, is_catalog_entry, created_at,
                           updated_at, partner_id, lot_id, source_document_id)
        SELECT r.id, CAST(:org AS uuid), r.shelf_id, pg_temp.uid('cat', r.cat), r.name, r.brand, r.uom,
               r.template_id, r.qty, r.recv_at::date, r.expiry,
               jsonb_build_object(
                 (:cat_keys)[r.cat * 3 + 1], pg_temp.fv((:cat_keys)[r.cat * 3 + 1], r.rec),
                 (:cat_keys)[r.cat * 3 + 2], pg_temp.fv((:cat_keys)[r.cat * 3 + 2], r.rec),
                 (:cat_keys)[r.cat * 3 + 3], pg_temp.fv((:cat_keys)[r.cat * 3 + 3], r.rec)),
               round(r.unit_cost, 2), :currency, false, false, r.recv_at,
               r.last_at,
               pg_temp.uid('sup', 1 + pg_temp.h(r.in_key, 32) % :suppliers), r.lot_id,
               pg_temp.uid('din', r.in_key)
        FROM scale_records r
        """,
    )
    add(
        'document lines',
        """
        INSERT INTO document_lines (id, document_id, item_id, product_template_id, name, brand,
                                    barcode, quantity, expected_quantity, done_quantity, uom_id,
                                    batch_number, expiry_date, unit_price, tax_rate, line_value,
                                    line_tax, line_gross, currency, line_number, source_po_line_id,
                                    product_snapshot, executed_location_id, target_location_id)
        SELECT pg_temp.uid('dli', r.rec), pg_temp.uid('din', r.in_key), r.id, r.template_id,
               r.name, r.brand, r.barcode, r.q0, r.q0, r.q0, r.uom, r.lot_name, r.expiry,
               round(r.unit_cost, 2), 23, round(r.q0 * r.unit_cost, 2),
               round(r.q0 * r.unit_cost * 0.23, 2), round(r.q0 * r.unit_cost * 1.23, 2),
               :currency, row_number() OVER (PARTITION BY r.in_key ORDER BY r.rec),
               CASE WHEN pg_temp.h(r.in_key, 34) % 4 = 0 THEN pg_temp.uid('pol', r.rec) END,
               jsonb_build_object('name', r.name, 'brand', r.brand),
               r.landed_id, r.landed_id
        FROM scale_records r
        """,
        """
        INSERT INTO document_lines (id, document_id, item_id, product_template_id, name, brand,
                                    barcode, quantity, expected_quantity, done_quantity, uom_id,
                                    batch_number, expiry_date, unit_price, tax_rate, line_value,
                                    line_tax, line_gross, currency, line_number,
                                    product_snapshot, executed_location_id, source_location_id)
        SELECT pg_temp.uid('dlo', o.ok), pg_temp.uid('dout', o.out_key), o.record_id,
               o.template_id, o.name, o.brand, o.barcode, o.qty, o.qty, o.qty, o.uom,
               o.lot_name, o.expiry, round(o.unit_cost * 1.35, 2), 23,
               round(o.qty * round(o.unit_cost * 1.35, 2), 2),
               round(o.qty * round(o.unit_cost * 1.35, 2) * 0.23, 2),
               round(o.qty * round(o.unit_cost * 1.35, 2) * 1.23, 2),
               :currency, row_number() OVER (PARTITION BY o.out_key ORDER BY o.ok),
               jsonb_build_object('name', o.name, 'brand', o.brand), o.shelf_id, o.shelf_id
        FROM scale_out o
        """,
        """
        INSERT INTO document_lines (id, document_id, item_id, product_template_id, name, brand,
                                    barcode, quantity, expected_quantity, done_quantity, uom_id,
                                    batch_number, expiry_date, currency, line_number,
                                    product_snapshot, executed_location_id, source_location_id,
                                    target_location_id)
        SELECT pg_temp.uid('dlt', r.rec), pg_temp.uid('dint', r.int_key), r.id, r.template_id,
               r.name, r.brand, r.barcode, r.q0, r.q0, r.q0, r.uom, r.lot_name, r.expiry,
               :currency, row_number() OVER (PARTITION BY r.int_key ORDER BY r.rec),
               jsonb_build_object('name', r.name, 'brand', r.brand),
               r.shelf_id, r.landed_id, r.shelf_id
        FROM scale_records r WHERE r.via_dock
        """,
    )
    add(
        'movements',
        """
        INSERT INTO stock_moves (id, organization_id, product_template_id, from_location_id,
                                 to_location_id, quantity, lot_id, expiry_date, state,
                                 reference_type, reference_id, created_by, created_at,
                                 updated_at, completed_at)
        SELECT pg_temp.uid('mvi', rec), CAST(:org AS uuid), template_id, NULL, landed_id, q0, lot_id, expiry,
               'done', 'document', pg_temp.uid('din', in_key), CAST(:user AS uuid), recv_at, recv_at, recv_at
        FROM scale_records
        """,
        """
        INSERT INTO stock_moves (id, organization_id, product_template_id, from_location_id,
                                 to_location_id, quantity, lot_id, expiry_date, state,
                                 reference_type, reference_id, created_by, created_at,
                                 updated_at, completed_at)
        SELECT pg_temp.uid('mvt', rec), CAST(:org AS uuid), template_id, landed_id, shelf_id, q0, lot_id,
               expiry, 'done', 'document', pg_temp.uid('dint', int_key), CAST(:user AS uuid), int_at, int_at,
               int_at
        FROM scale_records WHERE via_dock
        """,
        """
        INSERT INTO stock_moves (id, organization_id, product_template_id, from_location_id,
                                 to_location_id, quantity, lot_id, expiry_date, state,
                                 reference_type, reference_id, created_by, created_at,
                                 updated_at, completed_at)
        SELECT pg_temp.uid('mvo', ok), CAST(:org AS uuid), template_id, shelf_id, NULL, qty, lot_id, expiry,
               'done', 'document', pg_temp.uid('dout', out_key), CAST(:user AS uuid), at, at, at
        FROM scale_out
        """,
    )
    add(
        'cost layers',
        # What is left of each receipt, drained oldest first per product: the
        # newest receipts hold what the shelves hold today.
        """
        INSERT INTO stock_valuation_layers (id, organization_id, product_template_id,
                                            document_line_id, quantity, remaining_qty,
                                            unit_cost, total_value, document_date, currency,
                                            direction, cost_basis, created_at)
        SELECT pg_temp.uid('svi', rec), CAST(:org AS uuid), template_id, pg_temp.uid('dli', rec), q0,
               greatest(0, least(q0, on_hand - newer)), unit_cost, round(q0 * unit_cost, 2),
               recv_at::date, :currency, 'IN', 'stated', recv_at
        FROM (
          SELECT rec, template_id, q0, unit_cost, recv_at,
                 sum(qty) OVER (PARTITION BY template_id) AS on_hand,
                 coalesce(sum(q0) OVER (PARTITION BY template_id ORDER BY recv_at DESC, rec DESC
                                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS newer
          FROM scale_records
        ) layered
        """,
        """
        INSERT INTO stock_valuation_layers (id, organization_id, product_template_id,
                                            document_line_id, quantity, remaining_qty,
                                            unit_cost, total_value, currency, direction,
                                            cost_basis, item_id, created_at)
        SELECT pg_temp.uid('svo', ok), CAST(:org AS uuid), template_id, pg_temp.uid('dlo', ok), qty, 0,
               unit_cost, round(qty * unit_cost, 2), :currency, 'OUT', 'fifo', record_id, at
        FROM scale_out
        """,
    )
    add(
        'open work',
        # Purchase orders confirmed and their receipts expected, and dispatches
        # still in draft, naming stock that stands where they draw.
        """
        CREATE TEMP TABLE scale_open AS
        SELECT n, pg_temp.uid('sup', 1 + pg_temp.h(n, 41) % :suppliers) AS supplier_id,
               pg_temp.uid('cus', 1 + pg_temp.h(n, 42) % :customers) AS customer_id,
               (pg_temp.h(n, 43) % :warehouses)::int AS wh
        FROM generate_series(1, :open_documents) n
        """,
        """
        INSERT INTO purchase_orders (id, organization_id, number, status, partner_id,
                                     scheduled_date, currency, created_by, confirmed_by,
                                     confirmed_at, created_at, updated_at)
        SELECT pg_temp.uid('opo', n), CAST(:org AS uuid),
               'PO/' || extract(year FROM CAST(:now AS timestamptz))::int || '/'
                 || lpad(((SELECT count(*) FROM purchase_orders
                           WHERE organization_id = CAST(:org AS uuid)
                             AND number LIKE 'PO/' || extract(year FROM CAST(:now AS timestamptz))::int || '/%')
                          + n)::text, 6, '0'),
               'CONFIRMED', supplier_id, CAST(:now AS date) + (1 + n % 14)::int, :currency,
               CAST(:user AS uuid), CAST(:user AS uuid), CAST(:now AS timestamptz) - interval '1 day',
               CAST(:now AS timestamptz) - interval '2 days', CAST(:now AS timestamptz) - interval '1 day'
        FROM scale_open
        """,
        """
        INSERT INTO purchase_order_lines (id, purchase_order_id, product_template_id, name,
                                          quantity_ordered, quantity_received, unit_price,
                                          uom_id, tax_rate, line_number)
        SELECT pg_temp.uid('opol', o.n * 100 + l), pg_temp.uid('opo', o.n), p.id, p.name,
               10 + pg_temp.h(o.n * 100 + l, 44) % 90, 0, p.cost, p.uom, 23, l + 1
        FROM scale_open o CROSS JOIN generate_series(0, 14) l
        JOIN scale_products p ON p.i = 1 + pg_temp.h(o.n * 100 + l, 45) % :products
        """,
        """
        INSERT INTO documents (id, organization_id, type, number, status, partner_id,
                               partner_snapshot, target_location_id, source_location_id,
                               scheduled_date, currency, created_by, confirmed_by, created_at,
                               updated_at, confirmed_at)
        SELECT pg_temp.uid('oin', o.n), CAST(:org AS uuid), 'IN',
               'IN/' || extract(year FROM CAST(:now AS timestamptz))::int || '/'
                 || lpad(((SELECT count(*) FROM documents
                           WHERE organization_id = CAST(:org AS uuid)
                             AND number LIKE 'IN/' || extract(year FROM CAST(:now AS timestamptz))::int || '/%')
                          + o.n)::text, 6, '0'),
               'CONFIRMED', o.supplier_id, jsonb_build_object('name', sp.name, 'code', sp.code),
               pg_temp.uid('wh', o.wh), NULL, CAST(:now AS date) + (1 + o.n % 14)::int, :currency,
               CAST(:user AS uuid), CAST(:user AS uuid), CAST(:now AS timestamptz) - interval '1 day',
               CAST(:now AS timestamptz) - interval '1 day', CAST(:now AS timestamptz) - interval '1 day'
        FROM scale_open o JOIN scale_partners sp ON sp.id = o.supplier_id
        UNION ALL
        SELECT pg_temp.uid('oout', o.n), CAST(:org AS uuid), 'OUT',
               'OUT/' || extract(year FROM CAST(:now AS timestamptz))::int || '/'
                 || lpad(((SELECT count(*) FROM documents
                           WHERE organization_id = CAST(:org AS uuid)
                             AND number LIKE 'OUT/' || extract(year FROM CAST(:now AS timestamptz))::int || '/%')
                          + o.n)::text, 6, '0'),
               'DRAFT', o.customer_id, jsonb_build_object('name', sp.name, 'code', sp.code),
               NULL, pg_temp.uid('wh', o.wh), CAST(:now AS date) + (o.n % 3)::int, :currency,
               CAST(:user AS uuid), NULL, CAST(:now AS timestamptz) - interval '3 hours',
               CAST(:now AS timestamptz) - interval '3 hours', NULL
        FROM scale_open o JOIN scale_partners sp ON sp.id = o.customer_id
        """,
        """
        INSERT INTO document_lines (id, document_id, product_template_id, name, brand, barcode,
                                    quantity, expected_quantity, done_quantity, uom_id,
                                    unit_price, tax_rate, line_value, line_tax, line_gross,
                                    currency, line_number, source_po_line_id, product_snapshot,
                                    target_location_id)
        SELECT pg_temp.uid('oinl', o.n * 100 + l), pg_temp.uid('oin', o.n), pol.product_template_id,
               p.name, p.brand, p.barcode, pol.quantity_ordered, pol.quantity_ordered, 0, p.uom,
               pol.unit_price, 23, round(pol.quantity_ordered * pol.unit_price, 2),
               round(pol.quantity_ordered * pol.unit_price * 0.23, 2),
               round(pol.quantity_ordered * pol.unit_price * 1.23, 2), :currency, l + 1,
               pol.id, jsonb_build_object('name', p.name, 'brand', p.brand),
               pg_temp.uid('wh', o.wh)
        FROM scale_open o CROSS JOIN generate_series(0, 14) l
        JOIN purchase_order_lines pol ON pol.id = pg_temp.uid('opol', o.n * 100 + l)
        JOIN scale_products p ON p.id = pol.product_template_id
        """,
        """
        INSERT INTO document_lines (id, document_id, item_id, product_template_id, name, brand,
                                    barcode, quantity, expected_quantity, done_quantity, uom_id,
                                    batch_number, expiry_date, unit_price, tax_rate, line_value,
                                    line_tax, line_gross, currency, line_number, product_snapshot,
                                    source_location_id)
        SELECT pg_temp.uid('ooutl', o.n * 100 + l), pg_temp.uid('oout', o.n), r.id, r.template_id,
               r.name, r.brand, r.barcode, least(r.qty, 1 + l), least(r.qty, 1 + l), 0, r.uom,
               r.lot_name, r.expiry, round(r.unit_cost * 1.35, 2), 23,
               round(least(r.qty, 1 + l) * round(r.unit_cost * 1.35, 2), 2),
               round(least(r.qty, 1 + l) * round(r.unit_cost * 1.35, 2) * 0.23, 2),
               round(least(r.qty, 1 + l) * round(r.unit_cost * 1.35, 2) * 1.23, 2),
               :currency, l + 1, jsonb_build_object('name', r.name, 'brand', r.brand), r.shelf_id
        FROM scale_open o CROSS JOIN generate_series(0, 7) l
        JOIN LATERAL (
          SELECT * FROM scale_records r
          WHERE r.wh = o.wh AND r.qty >= 8
            AND r.rec >= (1 + pg_temp.h(o.n * 100 + l, 46) % :products)::bigint * 8
          ORDER BY r.rec LIMIT 1
        ) r ON true
        """,
        """
        UPDATE documents d
        SET total_net = t.net, total_tax = t.tax, total_gross = t.gross
        FROM (SELECT document_id, sum(line_value) AS net, sum(line_tax) AS tax,
                     sum(line_gross) AS gross
              FROM document_lines
              WHERE document_id IN (SELECT pg_temp.uid('oin', n) FROM scale_open
                                    UNION ALL SELECT pg_temp.uid('oout', n) FROM scale_open)
              GROUP BY document_id) t
        WHERE d.id = t.document_id
        """,
    )
    return groups


def _field_def_function() -> str:
    """``pg_temp.field_def(key)``: a category's declaration of one custom field."""
    cases = []
    for field in CUSTOM_FIELDS:
        definition = {
            'key': field['key'],
            'type': field['type'],
            'label': field['label'],
            'visible': True,
            'required': False,
            'is_system': False,
            **({'options': field['options']} if 'options' in field else {}),
        }
        literal = json.dumps(definition).replace("'", "''")
        cases.append(f"WHEN '{field['key']}' THEN '{literal}'::json")
    return f"""
        CREATE FUNCTION pg_temp.field_def(key text) RETURNS json
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$ SELECT CASE key {' '.join(cases)} END $$
    """


def _run_async(work):
    """Run *work(session)* on the application's async engine, which this script owns."""
    import asyncio

    from app import database

    async def _run():
        database.init_async_engine()
        try:
            async with database.AsyncSessionLocal() as adb:
                return await work(adb)
        finally:
            await database.async_engine.dispose()

    return asyncio.run(_run())


def _onboard_if_needed(org: Organization, user: User) -> None:
    """Make the organization a warehouse first, the way the setup screen does."""
    if org.onboarding_completed:
        return
    from app.core.contracts import UserContextDTO
    from app.services.onboarding_service import apply_onboarding_profile_async

    async def _apply(adb):
        fresh = await adb.get(Organization, org.id)
        await apply_onboarding_profile_async(
            adb,
            fresh,
            'equipment_wms',
            user=UserContextDTO(
                id=user.id, organization_id=org.id, role='admin', email=user.email
            ),
        )
        await adb.commit()

    _say('Onboarding the organization as a warehouse (equipment_wms)...')
    _run_async(_apply)


def _reconcile(org_id) -> dict:
    """The stock reconciliation's answer for the seeded organization."""
    from app.services.analytics.reconciliation import get_reconciliation_async

    async def _read(adb):
        return (await get_reconciliation_async(adb, org_id)).model_dump()

    return _run_async(_read)


def _resolve(db, email: str) -> dict:
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.organization_id:
        raise SystemExit(f'{email} not found — create the account before seeding.')
    org = db.get(Organization, user.organization_id)
    _onboard_if_needed(org, user)
    db.expire_all()
    org = db.get(Organization, user.organization_id)
    held = db.query(Item).filter(Item.organization_id == org.id).count()
    if held:
        raise SystemExit(
            f'The organization of {email} already holds {held} records; the scale '
            'seed writes into an empty one. Reset the database (make db-reset) first.'
        )
    return context(db, org, user)


def context(db, org: Organization, user: User) -> dict:
    """What the seed's statements need to know about the organization they fill."""

    def one(sql: str, **params):
        return db.execute(text(sql), params).scalar()

    return {
        'org': str(org.id),
        'user': str(user.id),
        'currency': org.currency or 'USD',
        'now': datetime.now(UTC).isoformat(),
        'pcs': str(
            one(
                "SELECT id FROM uoms WHERE organization_id IS NULL AND symbol = 'pcs' AND is_reference"
            )
        ),
        'box': str(
            one(
                "SELECT id FROM uoms WHERE organization_id IS NULL AND symbol = 'box' AND is_reference"
            )
        ),
        'shelf_type': one(
            "SELECT id::text FROM storage_types WHERE type_code = 'SHELF' "
            'AND (organization_id = :org OR organization_id IS NULL) '
            'ORDER BY organization_id NULLS LAST LIMIT 1',
            org=org.id,
        ),
        'room_type': one(
            "SELECT id::text FROM storage_types WHERE type_code = 'STORAGE_ROOM' "
            'AND (organization_id = :org OR organization_id IS NULL) '
            'ORDER BY organization_id NULLS LAST LIMIT 1',
            org=org.id,
        ),
    }


#: Every table the seed writes rows into.
SEEDED_TABLES = (
    'product_templates',
    'storage_locations',
    'items',
    'stock_lots',
    'stock_anchors',
    'stock_moves',
    'stock_valuation_layers',
    'documents',
    'document_lines',
    'purchase_orders',
    'purchase_order_lines',
    'partners',
    'categories',
)


def _set_secondary_indexes_aside(conn) -> list[str]:
    """Drop the seeded tables' secondary indexes; return the statements that rebuild them.

    Written row by row into ``items`` — 27 indexes, five of them trigram or
    GIN — a million products took over an hour; built once over the loaded
    table, each index is one sort. Only the indexes that check nothing are set
    aside: the primary keys, the unique indexes and every index behind a
    constraint stay, so a seeded row that broke one of their rules is refused
    as it would be anywhere. The drop and the rebuild run in the seed's own
    transaction, so a run that fails leaves the indexes as they were; for its
    length the tables are locked, which is why the seed runs on a stack of
    its own.
    """
    rows = conn.execute(
        text(
            """
            SELECT i.indexrelid::regclass::text, pg_get_indexdef(i.indexrelid)
            FROM pg_index i
            WHERE i.indrelid = ANY(CAST(:tables AS regclass[]))
              AND NOT i.indisunique AND NOT i.indisprimary
              AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)
            """
        ),
        {'tables': list(SEEDED_TABLES)},
    ).all()
    for name, _definition in rows:
        conn.execute(text(f'DROP INDEX {name}'))
    return [definition for _name, definition in rows]


def seed_organization(conn, ctx: dict, size: dict, seed: int) -> tuple[float, float]:
    """Write the organization through *conn* and commit; return the seconds it took.

    The first number is the writing and the index rebuild, the second adds the
    statistics. The session's helpers and work tables go with it at the end,
    so the connection is as it was handed over.
    """
    began = time.monotonic()
    steps = _Steps(conn)
    conn.execute(text('SET LOCAL synchronous_commit = off'))
    # Sized to the 2 GB docker-compose.prod.yml gives the database: a seed
    # statement holds several sorts and hashes at once, and a larger setting
    # gets the server killed for memory there instead of spilling to disk.
    conn.execute(text("SET LOCAL work_mem = '64MB'"))
    for statement in [
        *_functions(seed, ctx['org']),
        _custom_field_value_sql(),
        _field_def_function(),
    ]:
        conn.execute(text(statement))
    conn.execute(text("SET LOCAL maintenance_work_mem = '512MB'"))
    set_aside = _set_secondary_indexes_aside(conn)
    for label, statements in _seed_statements(ctx, size):
        steps.run(label, *statements)
    steps.run(f'indexes ({len(set_aside)} rebuilt)', *set_aside)
    conn.commit()
    written = time.monotonic() - began
    analyze_began = time.monotonic()
    for table in SEEDED_TABLES:
        conn.execute(text(f'ANALYZE {table}'))
    conn.execute(text('DISCARD TEMP'))
    conn.commit()
    _say(f'  {"analyze":<34} {"":>11}       {time.monotonic() - analyze_began:7.1f} s')
    return written, time.monotonic() - began


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument(
        '--products', type=int, required=True, help='number of products'
    )
    parser.add_argument(
        '--shelves',
        type=int,
        default=DEFAULT_SHELVES,
        help=f'shelves of the warehouse (default {DEFAULT_SHELVES:,})',
    )
    parser.add_argument(
        '--email', default=ADMIN_EMAIL, help='the account whose organization is seeded'
    )
    parser.add_argument(
        '--seed', type=int, default=1, help='hash seed (same seed, same data)'
    )
    args = parser.parse_args()
    if args.products < 1_000:
        parser.error('--products: at least 1000')

    size = _sizes(args.products, args.shelves)
    db = SessionLocal()
    try:
        ctx = _resolve(db, args.email)
    finally:
        db.close()

    _say(f'Seeding organization {ctx["org"]} at {args.products:,} products')
    _say('  ' + ', '.join(f'{k} {v:,}' for k, v in size.items()))

    from app.database import engine

    with engine.connect() as conn:
        written, total = seed_organization(conn, ctx, size, args.seed)
    _say(f'Written in {written:.0f} s, {total:.0f} s with the statistics.')

    _say('Reconciling...')
    reconciliation = _reconcile(ctx['org'])
    _say('  ' + ', '.join(f'{k} {v}' for k, v in reconciliation.items()))
    drift = (
        reconciliation['quant_move_drift_count']
        or reconciliation['layer_quant_drift_count']
    )
    if drift:
        _say('FAILED: the seeded stock does not reconcile.')
        return 1
    _say('Consistent: the shelves, the journal and the cost layers agree.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
