"""The exporter reads a payload writer's keys from its declaration.

A writer whose ``before``/``after`` are built from an update payload writes
no key as a literal, so the exporter cannot see it the way it sees dict
literals — it reads the ``AUDIT_PAYLOAD_SCHEMA`` declaration the writer
carries beside its own loop, resolves the two names through that file's
imports, and adds the intersection of the pair's fields, which is exactly
the set the writer's ``hasattr`` lets through.

The trap these tests guard is a name that means two classes in two modules:
a read schema and a model can share a name (``Item`` does), and resolving a
declaration by bare name would leak the read schema's fields — fields no
payload writer can ever journal — into the catalogue requirement.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / 'scripts' / 'export_audit_snapshot_keys.py'
)


def _load_script():
    spec = importlib.util.spec_from_file_location('export_audit_snapshot_keys', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def collect_keys():
    return _load_script().collect_keys


def _write_app(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / 'app'
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
    return root


def test_a_payload_declaration_contributes_the_schema_model_intersection(
    collect_keys, tmp_path: Path
) -> None:
    root = _write_app(
        tmp_path,
        {
            'schemas/thing.py': (
                'class ThingUpdate(BaseModel):\n'
                '    name: str | None = None\n'
                '    price: float | None = None\n'
                '    weight_uom_id: str | None = None\n'
            ),
            'models/thing.py': (
                'class Thing(Base):\n'
                '    name: str\n'
                '    price: float\n'
                '    is_deleted: bool\n'
            ),
            'services/thing_writes.py': (
                'from app.schemas.thing import ThingUpdate\n'
                'from app.models.thing import Thing\n'
                '\n'
                'AUDIT_PAYLOAD_SCHEMA = ("ThingUpdate", "Thing")\n'
            ),
        },
    )

    payload = collect_keys(root)

    # `weight_uom_id` the schema knows but the model does not: the writer's
    # `hasattr` strips it, so the journal can never show it. `is_deleted` the
    # model knows but no payload carries: likewise. Only the share is real.
    assert payload['keys'] == ['name', 'price']


def test_a_declared_name_resolves_through_the_writers_own_imports(
    collect_keys, tmp_path: Path
) -> None:
    """The read schema must not speak for the model it shares a name with.

    `Item` names both the model and the read schema; the read schema carries
    fields the model does not (a reader-side `freeze_date`, say). Resolving
    the declaration by bare name would journal those as if a payload could
    deliver them.
    """
    root = _write_app(
        tmp_path,
        {
            'schemas/item.py': (
                'class ItemUpdate(BaseModel):\n'
                '    name: str | None = None\n'
                '\n'
                '\n'
                'class Item(ItemBase):\n'
                '    name: str | None = None\n'
                '    freeze_date: str | None = None\n'
            ),
            'models/item.py': (
                'class Item(Base):\n    name: str\n    quantity: float\n'
            ),
            'services/item_writes.py': (
                'from app.schemas.item import ItemUpdate\n'
                'from app.models.item import Item\n'
                '\n'
                'AUDIT_PAYLOAD_SCHEMA = ("ItemUpdate", "Item")\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert 'name' in payload['keys']
    assert 'freeze_date' not in payload['keys'], (
        'the read schema answered for the model: a field no payload can '
        'carry entered the catalogue requirement'
    )


def test_a_field_named_apart_from_its_column_is_journalled_by_the_column(
    collect_keys, tmp_path: Path
) -> None:
    """The API's ``location_id`` is the ``storage_location_id`` column.

    The model carries the API name as a synonym, so both sides of the pair
    know ``location_id`` — but the writer dumps its payload keyed by column
    (``keyed_by_column``), and the journal shows the column. The artefact
    has to say what the journal says.
    """
    root = _write_app(
        tmp_path,
        {
            'schemas/_common.py': (
                "_COLUMN_FOR_FIELD = {'location_id': 'storage_location_id'}\n"
            ),
            'schemas/item.py': (
                'class ItemUpdate(BaseModel):\n'
                '    name: str | None = None\n'
                '    location_id: str | None = None\n'
            ),
            'models/item.py': (
                'class Item(Base):\n'
                '    name: str\n'
                '    storage_location_id: str\n'
                "    location_id: str = synonym('storage_location_id')\n"
            ),
            'services/item_writes.py': (
                'from app.schemas.item import ItemUpdate\n'
                'from app.models.item import Item\n'
                '\n'
                'AUDIT_PAYLOAD_SCHEMA = ("ItemUpdate", "Item")\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['keys'] == ['name', 'storage_location_id']


def test_a_writer_without_a_declaration_still_contributes_its_literals(
    collect_keys, tmp_path: Path
) -> None:
    root = _write_app(
        tmp_path,
        {
            'services/plain_writes.py': (
                'def log(snapshot):\n'
                '    return snapshot\n'
                '\n'
                '\n'
                'def do():\n'
                '    return log(snapshot={"reordered": True})\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['keys'] == ['reordered']
    assert payload['declarations-read'] == 0


def test_a_declaration_through_a_reexport_resolves(
    collect_keys, tmp_path: Path
) -> None:
    """A re-exported schema name resolves to the class it re-exports.

    A module's schemas live in a private file and are re-exported through
    the package's `schemas` (noqa: F401), and the writer imports — like
    every caller — from the public path. Python answers both spellings
    with the same class object; the declaration has to resolve the same
    way, or a writer whose import crosses a re-export reads as uncovered
    while its pair is perfectly declared.
    """
    root = _write_app(
        tmp_path,
        {
            'schemas/_thing.py': (
                'class ThingUpdate(BaseModel):\n    name: str | None = None\n'
            ),
            'schemas/__init__.py': ('from app.schemas._thing import ThingUpdate\n'),
            'models/thing.py': 'class Thing(Base):\n    name: str\n',
            'services/thing_config.py': (
                'from app.schemas import ThingUpdate\n'
                'from app.models.thing import Thing\n'
                '\n'
                'AUDIT_PAYLOAD_SCHEMA = ("ThingUpdate", "Thing")\n'
                '\n'
                '\n'
                'async def route(data):\n'
                '    await journal_config_change(\n'
                '        db, org, user,\n'
                '        module="m", subject="s",\n'
                '        keys=set(data.model_fields_set),\n'
                '        before={}, after={},\n'
                '    )\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['uncovered-writer-files'] == []
    assert 'name' in payload['keys']


def test_the_config_funnel_contributes_its_literal_keys(
    collect_keys, tmp_path: Path
) -> None:
    """A `keys=` argument is the writer's key universe, same as a snapshot.

    The configuration funnel (`journal_config_change`) takes the set of
    fields the request could have moved as `keys=`; when that set is a
    literal it is exactly as readable as a dict literal at a `snapshot=`
    call, and it belongs in the artefact the same way.
    """
    root = _write_app(
        tmp_path,
        {
            'services/config_writes.py': (
                'async def route():\n'
                '    await journal_config_change(\n'
                '        db, org, user,\n'
                '        module="m", subject="s",\n'
                '        keys={"approval_required", "approval_threshold"},\n'
                '        before={}, after={},\n'
                '    )\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert 'approval_required' in payload['keys']
    assert 'approval_threshold' in payload['keys']
    assert payload['uncovered-writer-files'] == []


def test_the_funnel_reads_its_context_and_skips_a_reference_name(
    collect_keys, tmp_path: Path
) -> None:
    """The record an entry is about is written beside the change (`context=`),
    and a name beside its id is how that id reads, in `keys=` as in a dict.
    """
    root = _write_app(
        tmp_path,
        {
            'services/config_writes.py': (
                'async def route():\n'
                '    await journal_config_change(\n'
                '        db, org, user,\n'
                '        module="m", subject="s",\n'
                '        keys={"limit", "shelf_id", "shelf_name"},\n'
                '        before={}, after={},\n'
                '        context={"bin_id": 1, "bin_name": "A"},\n'
                '    )\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert {'limit', 'shelf_id', 'bin_id'} <= set(payload['keys'])
    assert 'shelf_name' not in payload['keys']
    assert 'bin_name' not in payload['keys']


def test_a_dynamic_keys_site_without_a_declaration_is_counted(
    collect_keys, tmp_path: Path
) -> None:
    """A funnel writer that cuts its keys from a payload is visible.

    `keys=set(data.model_fields_set)` writes no literal, so the artefact
    cannot read the writer the way it reads one — but it can see that the
    writer exists, and say so. A file in that state is named in the
    artefact, and the gate refuses it: `green` must not mean `read
    everything that happened to declare itself`.
    """
    root = _write_app(
        tmp_path,
        {
            'schemas/thing.py': (
                'class ThingUpdate(BaseModel):\n    name: str | None = None\n'
            ),
            'models/thing.py': 'class Thing(Base):\n    name: str\n',
            'services/thing_config.py': (
                'async def route(data):\n'
                '    await journal_config_change(\n'
                '        db, org, user,\n'
                '        module="m", subject="s",\n'
                '        keys=set(data.model_fields_set),\n'
                '        before={}, after={},\n'
                '    )\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['uncovered-writer-files'] == ['app.services.thing_config']
    assert 'name' not in payload['keys']


def test_a_dynamic_keys_site_with_a_declaration_is_read(
    collect_keys, tmp_path: Path
) -> None:
    """The declaration closes the gap the dynamic keys cut open.

    Same writer as the counting test, plus the pair declaration: the
    artefact reads the writer (the schema/model intersection is exactly
    the universe `model_fields_set` can name) and stops naming the file
    as unread.
    """
    root = _write_app(
        tmp_path,
        {
            'schemas/thing.py': (
                'class ThingUpdate(BaseModel):\n'
                '    name: str | None = None\n'
                '    weight_uom_id: str | None = None\n'
            ),
            'models/thing.py': 'class Thing(Base):\n    name: str\n',
            'services/thing_config.py': (
                'from app.schemas.thing import ThingUpdate\n'
                'from app.models.thing import Thing\n'
                '\n'
                'AUDIT_PAYLOAD_SCHEMA = ("ThingUpdate", "Thing")\n'
                '\n'
                '\n'
                'async def route(data):\n'
                '    await journal_config_change(\n'
                '        db, org, user,\n'
                '        module="m", subject="s",\n'
                '        keys=set(data.model_fields_set),\n'
                '        before={}, after={},\n'
                '    )\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['uncovered-writer-files'] == []
    assert 'name' in payload['keys']
    assert 'weight_uom_id' not in payload['keys']


def test_a_declaration_that_names_nothing_covers_nothing(
    collect_keys, tmp_path: Path
) -> None:
    """A declaration is cover only when both of its names resolve.

    A typo in the pair (`ThingUpdte`) would otherwise read as a
    declaration the artefact counted and a file the gate trusted, while
    the writer's universe went unread — the same silent shape the
    declarations-read counter was saved to catch.
    """
    root = _write_app(
        tmp_path,
        {
            'schemas/thing.py': (
                'class ThingUpdate(BaseModel):\n    name: str | None = None\n'
            ),
            'models/thing.py': 'class Thing(Base):\n    name: str\n',
            'services/thing_config.py': (
                'from app.schemas.thing import ThingUpdate\n'
                'from app.models.thing import Thing\n'
                '\n'
                'AUDIT_PAYLOAD_SCHEMA = ("ThingUpdte", "Thing")\n'
                '\n'
                '\n'
                'async def route(data):\n'
                '    await journal_config_change(\n'
                '        db, org, user,\n'
                '        module="m", subject="s",\n'
                '        keys=set(data.model_fields_set),\n'
                '        before={}, after={},\n'
                '    )\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['uncovered-writer-files'] == ['app.services.thing_config']
    assert 'name' not in payload['keys']


def test_a_new_backend_file_does_not_change_the_saved_artefact() -> None:
    """The artefact moves with what the writers declare, not with the tree's size.

    It carried the count of files read, which grows with every new module
    anywhere in app/; the freshness gate ignores it, so the saved file went
    stale on its own and `make sync-audit-fields` on a clean tree produced a
    diff nobody had caused.
    """
    script = _load_script()
    declared = {
        'declarations-read': 4,
        'uncovered-writer-files': [],
        'keys': ['barcode', 'name'],
        'target-types': ['item'],
    }

    before = script.artefact_payload({**declared, 'files-read': 993})
    after = script.artefact_payload({**declared, 'files-read': 997})

    assert before == after
    assert before['keys'] == ['barcode', 'name']


def test_the_audit_target_types_are_read_from_the_enum(
    collect_keys, tmp_path: Path
) -> None:
    """Every value the journal can be filtered by is a member of one enum.

    The exporter reads the members, comments and docstring aside, so the
    frontend half can ask whether every one has a name in the catalogue.
    """
    root = _write_app(
        tmp_path,
        {
            'core/contracts/dtos.py': (
                'class AuditTargetType(StrEnum):\n'
                '    """What an entry is about."""\n'
                '\n'
                '    ITEM = "item"\n'
                '    #: A comment between members.\n'
                '    STOCK_LOT = "stock_lot"\n'
                '\n'
                '\n'
                'class Other(StrEnum):\n'
                '    NOT_A_TARGET = "not_a_target"\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['target-types'] == ['item', 'stock_lot']


def test_an_act_named_beside_the_changed_fields_is_read(
    collect_keys, tmp_path: Path
) -> None:
    """A journal helper that takes the act as `act=` writes those keys too.

    A purchase order's e-mail, line import and approval decision arrive in
    the entry through `act={...}`, beside the fields that moved; a key read
    from `snapshot=` alone left them out of the catalogue requirement and
    they reached the reader as the raw Python key.
    """
    root = _write_app(
        tmp_path,
        {
            'services/order_acts.py': (
                'async def route():\n'
                '    await journal_order_act(\n'
                '        db, org, user, po,\n'
                '        act={"emailed_to": addr, "approval": "approved"},\n'
                '    )\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert 'emailed_to' in payload['keys']
    assert 'approval' in payload['keys']
