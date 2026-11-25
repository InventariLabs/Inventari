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
        'values': ['status:open'],
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


def test_the_values_a_journalling_writer_can_show_come_from_every_typing_style(
    collect_keys, tmp_path: Path
) -> None:
    """An enum, a ``Literal`` alias and an allowed-set validator all name values.

    The writer that journals ``before``/``after`` shows a stored value under
    each journalled field; the values are read from the update schema's
    annotation or validator and from the model's column.
    """
    root = _write_app(
        tmp_path,
        {
            'schemas/thing.py': (
                'ALLOWED = frozenset({"A", "B"})\n'
                'UsageLiteral = Literal["internal", "customer"]\n'
                'class ThingUpdate(BaseModel):\n'
                '    kind: str | None = None\n'
                '    usage: UsageLiteral | None = None\n'
                '    state: ThingState | None = None\n'
                '    mode: Literal["x", "y"] | None = None\n'
                '    label: str | None = None\n'
                '    @field_validator("kind")\n'
                '    def check(cls, v):\n'
                '        return v if v in ALLOWED else None\n'
            ),
            'models/thing.py': (
                'class ThingState(str, Enum):\n'
                '    OPEN = "open"\n'
                '    SHUT = "shut"\n'
                'class Thing(Base):\n'
                '    kind: str\n'
                '    usage: str\n'
                '    state: Mapped[ThingState]\n'
                '    mode: str\n'
                '    label: str\n'
            ),
            'services/thing_writes.py': (
                'from app.schemas.thing import ThingUpdate\n'
                'from app.models.thing import Thing, ThingState\n'
                '\n'
                'AUDIT_PAYLOAD_SCHEMA = ("ThingUpdate", "Thing")\n'
                'snapshot = {"before": {}, "after": {}}\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['values'] == [
        'kind:A',
        'kind:B',
        'mode:x',
        'mode:y',
        'state:open',
        'state:shut',
        'usage:customer',
        'usage:internal',
    ]


def test_a_writer_that_journals_only_field_names_shows_no_value(
    collect_keys, tmp_path: Path
) -> None:
    """``'fields': changed`` names what moved and prints no stored value, so a
    status enum on its update schema is not a value the reader meets."""
    root = _write_app(
        tmp_path,
        {
            'schemas/thing.py': (
                'class ThingUpdate(BaseModel):\n'
                '    status: Literal["open", "shut"] | None = None\n'
            ),
            'models/thing.py': 'class Thing(Base):\n    status: str\n',
            'services/thing_writes.py': (
                'from app.schemas.thing import ThingUpdate\n'
                'from app.models.thing import Thing\n'
                '\n'
                'AUDIT_PAYLOAD_SCHEMA = ("ThingUpdate", "Thing")\n'
                'snapshot = {"fields": ["status"]}\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert 'status' in payload['keys']
    assert payload['values'] == []


def test_a_transition_snapshot_shows_the_values_of_the_column_it_moves(
    collect_keys, tmp_path: Path
) -> None:
    """A snapshot literal holding ``old_status`` and ``new_status`` prints a
    stored value under each key, whatever enum the imported model's column
    carries; a lone ``old_`` key is not a transition and names no value."""
    root = _write_app(
        tmp_path,
        {
            'models/thing.py': (
                'class ThingStatus(str, Enum):\n'
                '    OPEN = "open"\n'
                '    SHUT = "shut"\n'
                '\n'
                'class Thing(Base):\n'
                '    status: Mapped[ThingStatus]\n'
                '    name: str\n'
            ),
            'services/thing_writes.py': (
                'from app.models.thing import Thing\n'
                '\n'
                'snapshot = {"old_status": before, "new_status": after}\n'
                'lone = {"old_name": "a"}\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['values'] == [
        'new_status:open',
        'new_status:shut',
        'old_status:open',
        'old_status:shut',
    ]


def test_a_literal_written_under_a_transition_pair_is_a_value_the_journal_shows(
    collect_keys, tmp_path: Path
) -> None:
    """A status column typed as a plain string declares no set, so the codes a
    writer puts under ``old_<f>``/``new_<f>`` are read from its literals; a
    name or attribute there names no code, and a lone key is no transition."""
    root = _write_app(
        tmp_path,
        {
            'services/campaign_writes.py': (
                'snapshot = {"old_status": "DRAFT", "new_status": campaign.status}\n'
                'closing = {"old_status": previous, "new_status": "ARCHIVED"}\n'
                'lone = {"new_label": "ignored"}\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['values'] == ['new_status:ARCHIVED', 'old_status:DRAFT']


def test_a_code_in_the_status_set_of_the_writers_package_is_a_value_it_can_journal(
    collect_keys, tmp_path: Path
) -> None:
    """A writer that journals the status a column holds through a variable
    names no code itself; the field's set is the one its own package declares
    for it, so a code added there is enumerated for both shapes of snapshot
    (``old_``/``new_`` and ``before``/``after``). A set in another package, a
    set of the same package the writer spells no code of, and a field the
    writer does not journal as a value, add nothing."""
    root = _write_app(
        tmp_path,
        {
            'modules/shop/_schemas.py': (
                'ShopStatus = Literal["DRAFT", "ACTIVE", "ARCHIVED"]\n'
                '\n'
                'class ShopOut(BaseModel):\n'
                '    status: ShopStatus\n'
                '    label: Literal["not-journalled"]\n'
            ),
            'modules/shop/models.py': ('class Shop(Base):\n    status: Mapped[str]\n'),
            'modules/shop/_gauge.py': (
                'class GaugeOut(BaseModel):\n    status: Literal["ok", "over"]\n'
            ),
            'modules/shop/_writes.py': (
                'from app.modules.shop.models import Shop\n'
                '\n'
                'snapshot = {"old_status": "DRAFT", "new_status": shop.status}\n'
                'act(before={"status": previous}, after={"status": shop.status})\n'
            ),
            'modules/other/_schemas.py': (
                'class OtherOut(BaseModel):\n    status: Literal["ELSEWHERE"]\n'
            ),
        },
    )

    payload = collect_keys(root)

    assert payload['values'] == [
        'new_status:ACTIVE',
        'new_status:ARCHIVED',
        'new_status:DRAFT',
        'old_status:ACTIVE',
        'old_status:ARCHIVED',
        'old_status:DRAFT',
        'status:ACTIVE',
        'status:ARCHIVED',
        'status:DRAFT',
    ]


def test_a_code_in_a_status_set_the_writer_imports_is_a_value_it_can_journal(
    collect_keys, tmp_path: Path
) -> None:
    """A writer that journals a status through a variable gets the set from its
    own application module: the enum named for the model it imports, or else
    the key set of the transition table / collection it checks against. A set
    named for another model, a lone sentinel constant, an enum of the core
    contracts and the set of another module add nothing, whatever codes the
    writer's file spells."""
    root = _write_app(
        tmp_path,
        {
            'modules/shop/models.py': (
                'class DocStatus(StrEnum):\n'
                '    DRAFT = "DRAFT"\n'
                '    ARCHIVED = "ARCHIVED"\n'
                '\n'
                'class DocLineStatus(StrEnum):\n'
                '    LINE_OPEN = "LINE_OPEN"\n'
                '\n'
                'class Doc(Base):\n'
                '    status: Mapped[str]\n'
            ),
            'modules/shop/_writes.py': (
                'from .models import Doc\n'
                '\n'
                'doc.status = "pending"\n'
                'snapshot = {"old_status": old, "new_status": doc.status}\n'
            ),
            'modules/gear/_machine.py': (
                '_MOVES = {"AVAILABLE": {"GONE"}, "GONE": {"AVAILABLE"}}\n'
                'VALID_STATUSES = set(_MOVES.keys())\n'
                'UNKNOWN_STATUS = "UNKNOWN"\n'
                'def previous(value): return value\n'
            ),
            'modules/gear/_writes.py': (
                'from ._machine import previous\n'
                'from app.core.contracts import LotStatus\n'
                '\n'
                'snapshot = {"old_status": previous(x), "new_status": item.status}\n'
            ),
            'core/contracts.py': 'class LotStatus(StrEnum):\n    HELD = "held"\n    OK = "ok"\n',
            'modules/other/_status.py': 'OTHER_STATUSES = {"ELSEWHERE", "NOWHERE"}\n',
        },
    )

    payload = collect_keys(root)

    assert payload['values'] == [
        'new_status:ARCHIVED',
        'new_status:AVAILABLE',
        'new_status:DRAFT',
        'new_status:GONE',
        'old_status:ARCHIVED',
        'old_status:AVAILABLE',
        'old_status:DRAFT',
        'old_status:GONE',
    ]
