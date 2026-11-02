"""``manage.py demo fill-pool`` seeds visitors' sandboxes up to the pool size.

Seeding one takes seconds, so the count decides real work: a sandbox past
the day's cap is one no visitor may claim before the reset deletes it.
"""

import pytest

from app.cli.commands_demo import sandboxes_to_seed
from app.services.demo_sandbox_service import PoolState


@pytest.mark.parametrize(
    ('ready', 'claimed', 'target', 'cap', 'expected'),
    [
        (0, 0, 3, 200, 3),  # just after the reset: fill the pool
        (1, 40, 3, 200, 2),  # top up what the clicks took
        (3, 40, 3, 200, 0),  # full: nothing to do
        (0, 199, 3, 200, 1),  # one claim left today: one sandbox, not three
        (1, 199, 3, 200, 0),  # and it is already waiting
        (0, 200, 3, 200, 0),  # the cap is reached: seed nothing
        (5, 0, 3, 200, 0),  # a pool larger than asked is never negative work
    ],
)
def test_the_pool_is_topped_up_to_its_size_and_no_further_than_the_cap(
    ready: int, claimed: int, target: int, cap: int, expected: int
) -> None:
    state = PoolState(ready=ready, claimed=claimed)
    assert sandboxes_to_seed(state, target=target, cap=cap) == expected
