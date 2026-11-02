"""The guide's example module extends the warehouse through its seams.

``examples/lot_certificates`` is the module ``docs/MODULE_ADVANCED_GUIDE.md``
walks through: a certificate number required on every received lot, a
receipt that is not booked while that certificate is not on file, a pick
order by zone then weight, and a certificate column and filter on the
documents list. It is installed here the way a community module is — the
``module install`` command, unsigned, with the safety scan on and outside
the trusted set — and every seam it uses is then exercised through the
warehouse's own doors. When one of those seams changes shape, this is the
file that says so, before a module author does.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.cli import _module_meta, module_packaging
from app.core import module_migrations
from app.core._registry_class import ModuleRegistry
from app.core.contracts import ModuleModelBase, PickOrderLineDTO, PickOrderLocationDTO
from app.core.module_registry import module_registry
from app.core.module_safety import REPO_SHIPPED_MODULES, TRUSTED_SHIPPED_MODULES
from app.core.module_safety_analysis import analyze_module_safety
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse import (
    document_filters,
    pick_order_strategies,
    pre_post_checks,
)
from app.modules.warehouse.models import Document, DocumentStatus
from manage import app as cli
from tests.integration._shelf import run_in_async_session

MODULE = 'lot_certificates'
_URL = '/api/v1/warehouse/documents'


def _example_package() -> Path:
    """The package as it sits in the repository, next to the platform.

    The backend container sees the checkout at ``INVENTARI_REPO_ROOT``; on
    the host the file's own place leads to it. A missing package is a
    failure, not a skip: a skipped guard reads as a green one.
    """
    root = os.environ.get('INVENTARI_REPO_ROOT')
    repo = Path(root) if root else Path(__file__).resolve().parents[6]
    package = repo / 'examples' / MODULE
    if not (package / 'module.yaml').is_file():
        pytest.fail(f'the guide example is not at {package}')
    return package


@dataclass(frozen=True)
class _Installed:
    backend: Path
    frontend: Path
    output: str


@pytest.fixture(scope='module')
def installed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Installed]:
    """The example, installed by the CLI into an installation of its own."""
    root = tmp_path_factory.mktemp('installation')
    backend = root / 'backend_modules'
    frontend = root / 'frontend_modules'
    backend.mkdir()
    frontend.mkdir()
    # The installation the package goes into has the warehouse; the
    # installer's dependency check looks for its directory there.
    (backend / 'warehouse').mkdir()

    with pytest.MonkeyPatch.context() as patch:
        for target in (_module_meta, module_packaging):
            patch.setattr(target, 'BACKEND_MODULES_DIR', backend)
            patch.setattr(target, 'FRONTEND_MODULES_DIR', frontend)
        patch.setattr(_module_meta, 'TRACKING_FILE', root / 'tracking.json')
        patch.setattr(_module_meta, 'LEGACY_TRACKING_FILE', root / 'legacy.json')

        result = CliRunner().invoke(
            cli, ['module', 'install', str(_example_package()), '--allow-unsigned']
        )
        assert result.exit_code == 0, result.output

        import app.modules as app_modules

        patch.setattr(
            app_modules, '__path__', [str(backend), *list(app_modules.__path__)]
        )
        patch.setattr(module_migrations, 'MODULES_ROOT', backend)
        before = set(sys.modules)
        assert not ModuleModelBase.metadata.tables, 'a test left a module table'
        # What startup does with a module it finds on disk: the manifest, the
        # safety scan (the module is not one this repository ships, so the
        # scan holds it to the declared surface), the import, the catalogue.
        registry = ModuleRegistry()
        warehouse = module_registry.get('warehouse')
        assert warehouse is not None
        registry.register(warehouse)
        registry.discover_modules(base_path=backend)
        rejected = {r.module_name: r.reason for r in registry.get_rejected_modules()}
        assert MODULE not in rejected, rejected[MODULE]
        loaded = registry.get(MODULE)
        assert loaded is not None
        assert not loaded.metadata.is_trusted
        try:
            yield _Installed(backend / MODULE, frontend / MODULE, result.output)
        finally:
            for name in set(sys.modules) - before:
                if name == f'app.modules.{MODULE}' or name.startswith(
                    f'app.modules.{MODULE}.'
                ):
                    del sys.modules[name]
            ModuleModelBase.registry.dispose()
            ModuleModelBase.metadata.clear()
            # The warehouse's registries are process-wide: what the example
            # registered leaves with it, or a later test on this worker
            # lists a strategy no module behind it is loaded for.
            pre_post_checks._CHECKS.pop(MODULE, None)
            pick_order_strategies._STRATEGIES.pop('by_zone_then_weight', None)
            document_filters._FILTERS.pop((MODULE, 'certified'), None)


@pytest.fixture
def example(
    installed: _Installed, db_session: Session, doc_org: Organization
) -> Iterator[Any]:
    """The module enabled for the organization, its seams freshly plugged in.

    Other tests register their own stand-ins under this module's name; the
    module's ``register_seams`` puts its own back.
    """
    seams = importlib.import_module(f'app.modules.{MODULE}.seams')
    seams.register_seams()
    doc_org.enabled_modules = [*doc_org.enabled_modules, MODULE]
    db_session.commit()
    yield seams


@pytest.fixture
def register(example: Any, engine: Engine, db_session: Session) -> Iterator[None]:
    """The module's own table, built by its own migration chain.

    Torn down before the session's teardown, which treats a table the worker
    was not born with as a leftover of the test that made it.
    """
    url = engine.url.render_as_string(hide_password=False)
    db_session.commit()
    module_migrations.run_module_migrations(MODULE, 'upgrade', db_url=url)
    yield
    db_session.commit()
    module_migrations.run_module_migrations(MODULE, 'downgrade', db_url=url)
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS alembic_version_{MODULE}'))


def _file(engine: AsyncEngine, org: Organization, user: User, *numbers: str) -> None:
    # Imported by name: the package exists only once the fixture installed it.
    certificates = importlib.import_module(f'app.modules.{MODULE}.certificates')

    async def _put(session: AsyncSession) -> None:
        await certificates.file_certificates_async(session, org.id, numbers, user.id)
        await session.commit()

    run_in_async_session(engine, _put)


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    shelf: StorageLocation,
    template: ProductTemplate,
    *,
    number: str | None,
    lot: str | None = 'LOT-7',
) -> str:
    line: dict[str, Any] = {
        'product_template_id': str(template.id),
        'expected_quantity': 5,
    }
    if lot is not None:
        line['batch_number'] = lot
    if number is not None:
        line['meta_data'] = {MODULE: {'number': number}}
    created = client.post(
        _URL,
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(shelf.id),
            'lines': [line],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return cast(str, created.json()['id'])


def _status(db_session: Session, doc_id: str) -> str:
    db_session.expire_all()
    doc = db_session.get(Document, UUID(doc_id))
    assert doc is not None
    return doc.status


@pytest.mark.integration
class TestItInstallsAsACommunityModule:
    def test_the_installer_scans_it_and_it_is_not_one_of_ours(
        self, installed: _Installed
    ) -> None:
        assert 'Backend validation passed' in installed.output
        assert MODULE not in REPO_SHIPPED_MODULES
        assert MODULE not in TRUSTED_SHIPPED_MODULES
        # The scan the registry runs at every startup, on the copy that landed.
        assert (
            analyze_module_safety(installed.backend, ['database'], use_cache=False)
            == []
        )

    def test_the_warehouse_door_opens_only_with_the_declared_dependency(
        self, installed: _Installed, tmp_path: Path
    ) -> None:
        copy = tmp_path / MODULE
        shutil.copytree(installed.backend, copy)
        manifest = json.loads((copy / 'manifest.json').read_text(encoding='utf-8'))
        manifest['requires'] = []
        (copy / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

        refused = {
            finding.subject
            for finding in analyze_module_safety(copy, ['database'], use_cache=False)
            if finding.kind == 'off_surface_import'
        }

        assert refused == {'app.modules.warehouse.warehouse_api'}

    def test_its_screens_import_only_the_module_sdk(
        self, installed: _Installed
    ) -> None:
        """The frontend half reaches Core through ``@/module-sdk`` alone."""
        sources = sorted(
            [*installed.frontend.rglob('*.ts'), *installed.frontend.rglob('*.tsx')]
        )
        assert sources, 'the frontend half did not land'
        specifiers = {
            match
            for source in sources
            for match in re.findall(
                r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""",
                source.read_text(encoding='utf-8'),
            )
        }
        outside = {
            spec
            for spec in specifiers
            if spec.startswith('@/') and spec != '@/module-sdk'
        }
        packages = {spec for spec in specifiers if not spec.startswith(('@/', '.'))}

        assert outside == set()
        assert packages <= {'react', 'react-i18next', 'lucide-react'}


@pytest.mark.integration
class TestTheRequiredField:
    def test_a_lot_is_not_confirmed_without_its_certificate_number(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        example: Any,
    ) -> None:
        doc_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            number=None,
        )

        confirmed = client.patch(f'{_URL}/{doc_id}/confirm', headers=doc_auth_headers)

        assert confirmed.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = confirmed.json()['detail']
        assert detail['code'] == 'CERTIFICATE_NUMBER_MISSING'
        assert detail['message'] == 'Enter the certificate number for lot LOT-7.'
        assert _status(db_session, doc_id) == DocumentStatus.DRAFT.value

    def test_a_number_longer_than_the_register_keeps_is_not_confirmed(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        example: Any,
    ) -> None:
        """A number the register could not file is refused while it is typed."""
        doc_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            number='C' * 101,
        )

        confirmed = client.patch(f'{_URL}/{doc_id}/confirm', headers=doc_auth_headers)

        assert confirmed.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = confirmed.json()['detail']
        assert detail['code'] == 'CERTIFICATE_NUMBER_TOO_LONG'
        assert detail['message'] == (
            'The certificate number for lot LOT-7 is longer than 100 characters.'
        )
        assert _status(db_session, doc_id) == DocumentStatus.DRAFT.value

    def test_a_line_without_a_lot_asks_for_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        example: Any,
    ) -> None:
        doc_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            number=None,
            lot=None,
        )

        confirmed = client.patch(f'{_URL}/{doc_id}/confirm', headers=doc_auth_headers)

        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

    def test_the_number_filled_in_after_creation_lets_it_confirm(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        example: Any,
    ) -> None:
        """The document page's line slot writes the number through this door."""
        doc_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            number=None,
        )
        line_id = client.get(f'{_URL}/{doc_id}', headers=doc_auth_headers).json()[
            'lines'
        ][0]['id']

        saved = client.put(
            f'{_URL}/{doc_id}/lines/{line_id}/meta-data/{MODULE}',
            headers=doc_auth_headers,
            json={'number': 'C-17'},
        )
        assert saved.status_code == status.HTTP_200_OK, saved.text
        confirmed = client.patch(f'{_URL}/{doc_id}/confirm', headers=doc_auth_headers)

        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text


@pytest.mark.integration
class TestTheReceivingRule:
    def test_a_receipt_is_not_booked_while_its_certificate_is_not_on_file(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        register: None,
    ) -> None:
        doc_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            number='C-17',
        )
        confirmed = client.patch(f'{_URL}/{doc_id}/confirm', headers=doc_auth_headers)
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

        refused = client.patch(
            f'{_URL}/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert refused.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = refused.json()['detail']
        assert detail['code'] == 'CERTIFICATE_NOT_ON_FILE'
        assert detail['message'].startswith('Certificate C-17 is not on file.')
        assert _status(db_session, doc_id) == DocumentStatus.CONFIRMED.value

        _file(async_engine_fixture, doc_org, doc_user, 'C-17')
        completed = client.patch(
            f'{_URL}/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert completed.status_code == status.HTTP_200_OK, completed.text
        assert _status(db_session, doc_id) == DocumentStatus.COMPLETED.value

    def test_filing_a_number_longer_than_the_register_keeps_is_refused(
        self, example: Any
    ) -> None:
        """The filing request answers 422 instead of the column's error."""
        router = importlib.import_module(f'app.modules.{MODULE}.router')

        with pytest.raises(ValidationError, match='at most 100 characters'):
            router.FileCertificatesRequest(numbers=['C-1', 'C' * 101])
        assert router.FileCertificatesRequest(numbers=['C' * 100]).numbers

    def test_the_one_step_post_is_refused_whole(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        register: None,
    ) -> None:
        doc_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            number='C-404',
        )

        posted = client.post(f'{_URL}/{doc_id}/post', headers=doc_auth_headers)

        assert posted.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert posted.json()['detail']['code'] == 'CERTIFICATE_NOT_ON_FILE'
        # The confirmation ran in the same transaction and went with it.
        assert _status(db_session, doc_id) == DocumentStatus.DRAFT.value

    def test_another_organizations_certificate_is_not_this_ones(
        self,
        client: TestClient,
        async_engine_fixture: AsyncEngine,
        h: ModuleTestHelper,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        register: None,
    ) -> None:
        other = h.create_org('Another Org', ['core', 'warehouse', MODULE])
        _file(async_engine_fixture, other, doc_user, 'C-17')
        doc_id = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            number='C-17',
        )

        posted = client.post(f'{_URL}/{doc_id}/post', headers=doc_auth_headers)

        assert posted.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert posted.json()['detail']['code'] == 'CERTIFICATE_NOT_ON_FILE'


@pytest.mark.integration
class TestThePickOrder:
    def test_it_is_offered_under_the_modules_name(self, example: Any) -> None:
        owner, _ = pick_order_strategies.pick_order_strategies()['by_zone_then_weight']

        assert owner == MODULE

    def test_zone_by_zone_the_heaviest_line_first(
        self,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        h: ModuleTestHelper,
        doc_org: Organization,
        example: Any,
    ) -> None:
        light = h.create_template(doc_org, name='Washers')
        heavy = h.create_template(doc_org, name='Anvils')
        unweighed = h.create_template(doc_org, name='Labels')
        light.weight_value = Decimal('0.2')
        heavy.weight_value = Decimal('12')
        db_session.commit()

        def step(name: str, sequence: int) -> PickOrderLocationDTO:
            return PickOrderLocationDTO(
                id=UUID(int=sequence), sequence=sequence, short_code=name, name=name
            )

        zone_a, zone_b = step('A', 1), step('B', 2)

        def line(
            n: int, template: ProductTemplate, quantity: str, zone: Any
        ) -> PickOrderLineDTO:
            return PickOrderLineDTO(
                id=UUID(int=100 + n),
                product_template_id=template.id,
                quantity=Decimal(quantity),
                location_path=[zone, step(f'{zone.name}-{n}', 10 + n)],
            )

        lines = [
            line(1, light, '10', zone_b),  # 2 kg, in the second zone
            line(2, light, '5', zone_a),  # 1 kg
            line(3, unweighed, '50', zone_a),  # nobody weighed it
            line(4, heavy, '1', zone_a),  # 12 kg
            PickOrderLineDTO(id=UUID(int=999), quantity=Decimal(1)),  # no shelf
        ]
        label = {entry.id: entry.id.int - 100 for entry in lines[:4]}
        label[UUID(int=999)] = 0

        async def _walk(session: AsyncSession) -> list[int]:
            ordered = await example.by_zone_then_weight(session, doc_org.id, lines)
            return [label[entry.id] for entry in ordered]

        # Zone A heaviest first, the unweighed last in it; then zone B; then
        # the line with no shelf.
        assert run_in_async_session(async_engine_fixture, _walk) == [4, 2, 3, 1, 0]


@pytest.mark.integration
class TestTheRegisterFilter:
    def test_the_certified_chip_keeps_the_lots_whose_certificate_is_on_file(
        self,
        client: TestClient,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        register: None,
    ) -> None:
        """Certified means what the receiving rule means: on file, as written.

        A blank number, a number nobody filed and a line with no lot are not
        certified; the number is matched as the line wrote it, the way the
        rule matches it, so a padded one filed as written counts.
        """

        def receipt(number: str | None, lot: str | None = 'LOT-7') -> str:
            return _receipt(
                client,
                doc_auth_headers,
                doc_partner,
                doc_target_location,
                doc_template,
                number=number,
                lot=lot,
            )

        filed = receipt('C-17')
        padded = receipt(' C-19 ')
        for number in ('', '   ', 'C-18'):
            receipt(number)
        receipt(None, lot=None)
        _file(async_engine_fixture, doc_org, doc_user, 'C-17', ' C-19 ')

        listed = client.get(
            _URL,
            headers=doc_auth_headers,
            params={'module_filter': f'{MODULE}:certified'},
        )

        assert listed.status_code == status.HTTP_200_OK, listed.text
        body = listed.json()
        assert sorted(row['id'] for row in body['items']) == sorted([filed, padded])
        assert body['total'] == 2
        posted = client.post(f'{_URL}/{padded}/post', headers=doc_auth_headers)
        assert posted.status_code == status.HTTP_200_OK, posted.text

    def test_with_nothing_on_file_nothing_is_certified(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        register: None,
    ) -> None:
        _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            doc_template,
            number='C-17',
        )

        listed = client.get(
            _URL,
            headers=doc_auth_headers,
            params={'module_filter': f'{MODULE}:certified'},
        )

        assert listed.status_code == status.HTTP_200_OK, listed.text
        assert listed.json()['total'] == 0


@pytest.mark.integration
def test_the_guide_quotes_the_modules_own_files() -> None:
    """The worked example's code blocks are the module's files, verbatim.

    The chapter used to carry snippets of a module nobody ran; they drifted
    from the registries they named. Each block marked ``example-file`` must
    read exactly as the file it names.
    """
    package = _example_package()
    guide = (package.parents[1] / 'docs' / 'MODULE_ADVANCED_GUIDE.md').read_text(
        encoding='utf-8'
    )
    quoted = re.findall(
        r'<!-- example-file: (\S+) -->\n```\w+\n(.*?)\n```\n', guide, re.DOTALL
    )

    assert [path for path, _ in quoted] == [
        'backend/seams.py',
        'frontend/module.ts',
        'frontend/components/CertificateField.tsx',
    ]
    for path, code in quoted:
        assert code == (package / path).read_text(encoding='utf-8').rstrip('\n'), path
