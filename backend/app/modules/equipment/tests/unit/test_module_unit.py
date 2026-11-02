"""
Unit tests for equipment module.py — EquipmentModule lifecycle methods.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.modules.equipment.module import EquipmentModule


@pytest.mark.unit
class TestEquipmentModule:
    def test_metadata(self) -> None:
        m = EquipmentModule()
        assert m.metadata is not None
        assert m.metadata.name == 'equipment'

    def test_register_routes(self) -> None:
        m = EquipmentModule()
        router = m.register_routes()
        assert router is not None

    def test_register_contributions(self) -> None:
        with patch('app.core.contributions.contribution_registry') as mock_reg:
            EquipmentModule().register_contributions()
            # Registers item_interceptors + upload_path_resolvers.
            assert mock_reg.register.call_count == 2
            points = [c.args[0] for c in mock_reg.register.call_args_list]
            assert 'item_interceptors' in points
            assert 'upload_path_resolvers' in points

    def test_on_startup_registers_tasks(self) -> None:
        with patch('app.core.scheduler.task_scheduler') as mock_scheduler:
            with patch('app.modules.equipment.module.BaseModule'):
                m = EquipmentModule()
                ctx = MagicMock()
                m.on_startup(ctx)
                assert mock_scheduler.register.call_count == 2
                names = [
                    c.kwargs.get('name') for c in mock_scheduler.register.call_args_list
                ]
                assert 'attestation_reminder_check' in names
                assert 'equipment_notification_check' in names

    def test_on_startup_scheduler_unavailable(self) -> None:
        with patch(
            'app.core.scheduler.task_scheduler',
            side_effect=ImportError,
            create=True,
        ):
            with patch('app.modules.equipment.module.BaseModule'):
                m = EquipmentModule()
                ctx = MagicMock()
                m.on_startup(ctx)

    async def test_attestation_reminder_worker(self) -> None:
        with patch(
            'app.modules.equipment.attestation_service.run_attestation_reminder_self_contained'
        ) as mock_run:
            m = EquipmentModule()
            await m._attestation_reminder_worker()
            mock_run.assert_called_once()

    async def test_attestation_reminder_worker_exception(self) -> None:
        with patch(
            'app.modules.equipment.attestation_service.run_attestation_reminder_self_contained',
            side_effect=RuntimeError('boom'),
        ):
            m = EquipmentModule()
            await m._attestation_reminder_worker()

    async def test_equipment_notification_worker(self) -> None:
        with patch(
            'app.modules.equipment.notification_worker.run_notification_check_self_contained'
        ) as mock_run:
            m = EquipmentModule()
            await m._equipment_notification_worker()
            mock_run.assert_called_once()

    async def test_equipment_notification_worker_exception(self) -> None:
        with patch(
            'app.modules.equipment.notification_worker.run_notification_check_self_contained',
            side_effect=RuntimeError('boom'),
        ):
            m = EquipmentModule()
            await m._equipment_notification_worker()

    def test_metadata_declares_default_storage_locations(self) -> None:
        """The seed moved to metadata declarations, applied by
        the framework ``system_on_enable`` on every enable path."""
        m = EquipmentModule()
        decls = m.metadata.default_storage_locations
        assert {d.name for d in decls} == {
            'Main Warehouse',
            'Server Room',
            'IT Storage',
        }
        untagged = [d for d in decls if d.context_tag is None]
        assert [d.name for d in untagged] == ['Main Warehouse']
        assert [d.behavior_mode for d in untagged] == ['STOCK']
        assert all(
            d.context_tag == 'equipment' for d in decls if d.context_tag is not None
        )
        assert all(
            d.behavior_mode == 'NONE' for d in decls if d.context_tag is not None
        )
