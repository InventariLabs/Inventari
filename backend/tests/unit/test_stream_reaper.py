"""One reaper pass reclaims first, then forgets the dead consumers of both groups."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.core.stream_reaper import DEAD_CONSUMER_IDLE_MS, reap_streams_once


async def test_a_pass_prunes_dead_consumers_of_the_event_and_task_groups_after_reclaiming():
    order: list[str] = []

    def recorded(name: str, result: int = 0) -> AsyncMock:
        async def run(*args):
            order.append(f'{name}{args}')
            return result

        return AsyncMock(side_effect=run)

    bus, scheduler = MagicMock(), MagicMock()
    bus.reclaim_pending_events = recorded('reclaim_events')
    scheduler.reclaim_pending_tasks = recorded('reclaim_tasks')
    bus.prune_dead_consumers = recorded('prune_events')
    scheduler.prune_dead_consumers = recorded('prune_tasks')

    with (
        patch('app.core.stream_reaper.event_bus', bus),
        patch('app.core.stream_reaper.task_scheduler', scheduler),
    ):
        await reap_streams_once()

    idle = (DEAD_CONSUMER_IDLE_MS,)
    assert order == [
        'reclaim_events()',
        'reclaim_tasks()',
        f'prune_events{idle}',
        f'prune_tasks{idle}',
    ]
