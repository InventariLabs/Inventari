"""Tests for ``app.services.storage_hierarchy_service``.

``_infer_behavior_mode`` is pure and unit-tested. ``create_storage_hierarchy``
resolves or creates each step of a location chain of any length against a
real ``AsyncSession``. Every created level — intermediate steps included —
goes through the audited ``_writes.create_storage``: the leaf-only cases stub
it to inspect the payload the writer receives, while the chain cases let it
run so the rows and their journal entries are real.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import NotFoundException
from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditAction, AuditLog, AuditTargetType
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.schemas.storage_location import (
    StorageHierarchyCreate,
    StorageLocationCreate,
    StorageTypeInlineCreate,
)
from app.services.storage_hierarchy_service import (
    _infer_behavior_mode,
    create_storage_hierarchy,
)


@pytest.mark.unit
class TestInferBehaviorMode:
    def test_freeze_date_returns_freezing(self) -> None:
        assert _infer_behavior_mode(['quantity', 'freeze_date']) == 'FREEZING'

    def test_expiry_date_returns_expiry(self) -> None:
        assert _infer_behavior_mode(['expiry_date', 'quantity']) == 'EXPIRY'

    def test_other_returns_stock(self) -> None:
        assert _infer_behavior_mode(['quantity']) == 'STOCK'
        assert _infer_behavior_mode([]) == 'STOCK'


@pytest.fixture
async def hierarchy_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Hierarchy Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def hierarchy_user(
    real_async_db_session: AsyncSession, hierarchy_org: Organization
) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        hierarchy_org,
        email='hierarchy@example.com',
        role='admin',
    )


def _ctx(user: User) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


async def _location(
    db: AsyncSession,
    org: Organization,
    user: User,
    name: str,
    parent_id: UUID | None = None,
) -> StorageLocation:
    location = StorageLocation(
        organization_id=org.id,
        created_by=user.id,
        name=name,
        parent_id=parent_id,
    )
    db.add(location)
    await db.flush()
    return location


async def _storage_type(
    db: AsyncSession,
    org: Organization,
    *,
    name: str,
    type_code: str,
    behavior_mode: str,
    context_schema: list[str],
) -> StorageType:
    storage_type = StorageType(
        organization_id=org.id,
        name=name,
        type_code=type_code,
        behavior_mode=behavior_mode,
        context_schema=context_schema,
        field_definitions=[],
    )
    db.add(storage_type)
    await db.flush()
    return storage_type


@pytest.mark.integration
class TestCreateStorageHierarchy:
    async def test_existing_parent_and_step_ids(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        site = await _location(
            real_async_db_session, hierarchy_org, hierarchy_user, 'Site A'
        )
        zone = await _location(
            real_async_db_session,
            hierarchy_org,
            hierarchy_user,
            'Zone A',
            parent_id=site.id,
        )

        created = MagicMock()
        created.id = uuid.uuid4()
        with (
            patch(
                'app.services.storage._writes.create_storage',
                new_callable=AsyncMock,
                return_value=created,
            ) as mock_create,
        ):
            result = await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(
                    parent_id=site.id,
                    steps=[{'id': zone.id}, {'name': 'Shelf A'}],
                    context_schema=['expiry_date'],
                ),
                _ctx(hierarchy_user),
            )

        assert result is created
        storage_in = mock_create.call_args.args[1]
        assert isinstance(storage_in, StorageLocationCreate)
        assert storage_in.parent_id == zone.id
        assert storage_in.behavior_mode == 'EXPIRY'
        assert storage_in.context_tag == 'food'
        assert storage_in.context_schema == ['expiry_date']

    async def test_parent_id_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        with pytest.raises(NotFoundException):
            await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(
                    parent_id=uuid.uuid4(), steps=[{'name': 'Shelf'}]
                ),
                _ctx(hierarchy_user),
            )

    async def test_step_id_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        site = await _location(
            real_async_db_session, hierarchy_org, hierarchy_user, 'Site A'
        )
        with pytest.raises(NotFoundException):
            await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(
                    parent_id=site.id,
                    steps=[{'id': uuid.uuid4()}, {'name': 'Shelf'}],
                ),
                _ctx(hierarchy_user),
            )

    async def test_creates_new_names_down_the_chain(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        created = await create_storage_hierarchy(
            real_async_db_session,
            StorageHierarchyCreate(
                steps=[
                    {'name': 'Warehouse'},
                    {'name': 'Zone A'},
                    {'name': 'Shelf A'},
                ],
                context_schema=[],
            ),
            _ctx(hierarchy_user),
        )

        locations = (
            await real_async_db_session.scalars(
                select(StorageLocation).where(
                    StorageLocation.organization_id == hierarchy_org.id
                )
            )
        ).all()
        by_name = {loc.name: loc for loc in locations}
        # A chain with no explicit parent hangs under nothing: the first
        # step it names IS the root, the same shape as every seeded
        # warehouse and as the one StorageRequired makes.
        assert by_name['Warehouse'].parent_id is None
        assert by_name['Zone A'].parent_id == by_name['Warehouse'].id
        assert created.parent_id == by_name['Zone A'].id

    async def test_every_level_of_the_chain_earns_a_journal_entry(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        """The intermediate step is a place the journal has to be able to name.

        The chain creator wrote its intermediate levels straight through the
        model while only the leaf went through the audited writer, so the
        journal held entries reading "Parent: Warehouse" for a warehouse
        whose own creation was never written down. One entry per created
        level, the intermediate one included — and naming a level that
        already exists adds no second entry for it.
        """
        ctx = _ctx(hierarchy_user)
        await create_storage_hierarchy(
            real_async_db_session,
            StorageHierarchyCreate(steps=[{'name': 'Warehouse'}, {'name': 'Shelf A'}]),
            ctx,
        )
        await create_storage_hierarchy(
            real_async_db_session,
            StorageHierarchyCreate(steps=[{'name': 'Warehouse'}, {'name': 'Shelf B'}]),
            ctx,
        )

        entries = (
            await real_async_db_session.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == hierarchy_org.id,
                    AuditLog.action == AuditAction.CREATE,
                    AuditLog.target_type == AuditTargetType.STORAGE,
                )
            )
        ).all()
        by_name = {entry.snapshot['name']: entry for entry in entries}
        assert set(by_name) == {'Warehouse', 'Shelf A', 'Shelf B'}
        assert by_name['Warehouse'].snapshot['parent_name'] is None
        assert by_name['Shelf A'].snapshot['parent_name'] == 'Warehouse'
        assert by_name['Shelf B'].snapshot['parent_name'] == 'Warehouse'

    async def test_duplicate_sibling_name_raises(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        with (
            patch(
                'app.services.storage._writes._check_name_unique',
                new_callable=AsyncMock,
                side_effect=ValueError('duplicate'),
            ),
        ):
            with pytest.raises(ValueError, match='duplicate'):
                await create_storage_hierarchy(
                    real_async_db_session,
                    StorageHierarchyCreate(steps=[{'name': 'Dup'}, {'name': 'Shelf'}]),
                    _ctx(hierarchy_user),
                )

    async def test_one_named_step_becomes_a_root(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        created = MagicMock()
        created.id = uuid.uuid4()
        with patch(
            'app.services.storage._writes.create_storage',
            new_callable=AsyncMock,
            return_value=created,
        ) as mock_create:
            await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(steps=[{'name': 'Shelf A'}]),
                _ctx(hierarchy_user),
            )

        storage_in = mock_create.call_args.args[1]
        assert storage_in.parent_id is None

    async def test_org_required_raises(
        self, real_async_db_session: AsyncSession
    ) -> None:
        user = UserContextDTO(id=uuid.uuid4(), organization_id=None, role='admin')
        with pytest.raises(ValueError, match='Organization required'):
            await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(steps=[{'name': 'Shelf'}]),
                user,
            )

    async def test_inline_storage_type_created(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        created = MagicMock()
        created.id = uuid.uuid4()
        with (
            patch(
                'app.services.label_service.generate_short_code_async',
                new_callable=AsyncMock,
                return_value='LOC-AAAA',
            ),
            patch(
                'app.services.storage._writes.create_storage',
                new_callable=AsyncMock,
                return_value=created,
            ) as mock_create,
        ):
            await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(
                    steps=[{'name': 'Shelf A'}],
                    location_type=StorageTypeInlineCreate(
                        name='Custom Cold Room',
                        type_code='CUSTOM COLD-ROOM',
                        behavior_mode='EXPIRY',
                        context_schema=['expiry_date'],
                    ),
                    context_schema=[],
                ),
                _ctx(hierarchy_user),
            )

        created_type = await real_async_db_session.scalar(
            select(StorageType).where(StorageType.name == 'Custom Cold Room')
        )
        assert created_type is not None
        assert created_type.type_code.startswith('CUSTOMCOLDROOM_')

        storage_in = mock_create.call_args.args[1]
        assert storage_in.location_type_id == created_type.id
        assert storage_in.behavior_mode == 'EXPIRY'
        assert storage_in.context_tag == 'food'

    async def test_existing_storage_type_id_is_linked(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        storage_type = await _storage_type(
            real_async_db_session,
            hierarchy_org,
            name='Freezer Type',
            type_code='FREEZER_TYPE',
            behavior_mode='FREEZING',
            context_schema=['freeze_date', 'quantity'],
        )
        storage_type.field_definitions = [
            {'key': 'freeze_note', 'label': 'Freeze note', 'type': 'text'}
        ]
        await real_async_db_session.flush()

        created = MagicMock()
        created.id = uuid.uuid4()
        with patch(
            'app.services.storage._writes.create_storage',
            new_callable=AsyncMock,
            return_value=created,
        ) as mock_create:
            await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(
                    steps=[{'name': 'Shelf A'}],
                    location_type_id=storage_type.id,
                    context_schema=[],
                ),
                _ctx(hierarchy_user),
            )

        storage_in = mock_create.call_args.args[1]
        assert storage_in.location_type_id == storage_type.id
        assert storage_in.behavior_mode == 'FREEZING'
        assert storage_in.context_tag == 'food'
        assert len(storage_in.field_definitions) == 1
        assert storage_in.field_definitions[0].key == 'freeze_note'
        assert storage_in.field_definitions[0].label == 'Freeze note'

    async def test_unknown_storage_type_id_falls_back_to_stock(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        created = MagicMock()
        created.id = uuid.uuid4()
        with patch(
            'app.services.storage._writes.create_storage',
            new_callable=AsyncMock,
            return_value=created,
        ) as mock_create:
            await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(
                    steps=[{'name': 'Shelf A'}],
                    location_type_id=uuid.uuid4(),
                    context_schema=[],
                ),
                _ctx(hierarchy_user),
            )

        storage_in = mock_create.call_args.args[1]
        assert storage_in.behavior_mode == 'STOCK'
        assert storage_in.context_tag is None

    async def test_explicit_context_tag_is_preserved(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        created = MagicMock()
        created.id = uuid.uuid4()
        with patch(
            'app.services.storage._writes.create_storage',
            new_callable=AsyncMock,
            return_value=created,
        ) as mock_create:
            await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(
                    steps=[{'name': 'Shelf A'}],
                    context_schema=['expiry_date'],
                    context_tag='equipment',
                ),
                _ctx(hierarchy_user),
            )

        storage_in = mock_create.call_args.args[1]
        assert storage_in.context_tag == 'equipment'

    async def test_a_chain_of_five_is_walked_step_by_step(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        """Ids and names interleave down a path longer than the old three.

        A chain of three fits the site/zone/leaf shape the endpoints used to
        take, so a test of three steps cannot tell walking from guessing.
        This one is five deep and switches between id and name on the way
        down: resolving only one of the two shapes hangs the leaf on the
        wrong parent.
        """
        first = await _location(
            real_async_db_session, hierarchy_org, hierarchy_user, 'Harbor'
        )
        second = await _location(
            real_async_db_session,
            hierarchy_org,
            hierarchy_user,
            'Shed 1',
            parent_id=first.id,
        )

        created = await create_storage_hierarchy(
            real_async_db_session,
            StorageHierarchyCreate(
                parent_id=first.id,
                steps=[
                    {'name': 'Shed 1'},
                    {'id': second.id},
                    {'name': 'Rack 2'},
                    {'name': 'Bin 3'},
                    {'name': 'Tray 4'},
                ],
                context_schema=[],
            ),
            _ctx(hierarchy_user),
        )

        rows = (
            await real_async_db_session.scalars(
                select(StorageLocation).where(
                    StorageLocation.organization_id == hierarchy_org.id
                )
            )
        ).all()
        by_name = {row.name: row for row in rows}
        assert by_name['Rack 2'].parent_id == second.id
        assert by_name['Bin 3'].parent_id == by_name['Rack 2'].id
        assert created.parent_id == by_name['Bin 3'].id


@pytest.mark.integration
class TestTheChainInventsNoRootAtAll:
    """What the chain names is what the chain creates, and nothing above it.

    ``_resolve_root`` used to answer a chain with no parent by creating a
    top-level location named after the organization, flagged
    ``settings.is_default_site``, and hanging the reader's warehouse beneath
    it. The storages card then wore an overline nobody had typed, the
    archive dialog offered "QA Many › Magazyn › Regał" beside six paths that
    started at a warehouse, and the invented level could not be deleted from
    the interface. The organization is not a place; it owns them.
    """

    async def test_a_chain_under_an_existing_location_invents_nothing(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        site = await _location(
            real_async_db_session, hierarchy_org, hierarchy_user, 'Warsaw Office'
        )
        created = MagicMock()
        created.id = uuid.uuid4()

        with patch(
            'app.services.storage._writes.create_storage',
            new_callable=AsyncMock,
            return_value=created,
        ) as mock_create:
            await create_storage_hierarchy(
                real_async_db_session,
                StorageHierarchyCreate(
                    steps=[{'id': site.id}, {'name': 'Probe Shelf'}]
                ),
                _ctx(hierarchy_user),
            )

        assert mock_create.call_args.args[1].parent_id == site.id

    async def test_a_chain_that_names_its_first_step_creates_two_rows(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        """The measurement of the report: two rows, and the first is a root.

        The wizard's two steps produced three locations — the third, created
        eight milliseconds before the warehouse the reader asked for, carried
        the organization's name.
        """
        before = len(
            (
                await real_async_db_session.scalars(
                    select(StorageLocation).where(
                        StorageLocation.organization_id == hierarchy_org.id
                    )
                )
            ).all()
        )

        await create_storage_hierarchy(
            real_async_db_session,
            StorageHierarchyCreate(
                steps=[{'name': 'Warsaw Office'}, {'name': 'Probe Shelf'}]
            ),
            _ctx(hierarchy_user),
        )

        rows = (
            await real_async_db_session.scalars(
                select(StorageLocation).where(
                    StorageLocation.organization_id == hierarchy_org.id
                )
            )
        ).all()
        assert len(rows) - before == 2
        by_name = {row.name: row for row in rows}
        assert by_name['Warsaw Office'].parent_id is None
        assert by_name['Probe Shelf'].parent_id == by_name['Warsaw Office'].id
        assert not any(row.name == hierarchy_org.name for row in rows[before:])

    async def test_a_single_existing_step_leaves_the_organization_as_it_was(
        self,
        real_async_db_session: AsyncSession,
        hierarchy_org: Organization,
        hierarchy_user: User,
    ) -> None:
        # The shape the wizard sends when the reader picks a location and
        # names nothing: it must not be a write at all. Counted against the
        # database rather than a mock, because the extra root was a row.
        site = await _location(
            real_async_db_session, hierarchy_org, hierarchy_user, 'Warsaw Office'
        )
        await real_async_db_session.commit()

        before = len(
            (
                await real_async_db_session.scalars(
                    select(StorageLocation).where(
                        StorageLocation.organization_id == hierarchy_org.id
                    )
                )
            ).all()
        )

        result = await create_storage_hierarchy(
            real_async_db_session,
            StorageHierarchyCreate(steps=[{'id': site.id}]),
            _ctx(hierarchy_user),
        )

        after = (
            await real_async_db_session.scalars(
                select(StorageLocation).where(
                    StorageLocation.organization_id == hierarchy_org.id
                )
            )
        ).all()
        assert result.id == site.id
        assert len(after) == before
