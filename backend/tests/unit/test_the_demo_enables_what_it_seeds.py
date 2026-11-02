"""Nothing the demo seeds may land in a module the demo leaves switched off.

Found by opening the screen rather than by reading the code. ``demo reset``
reported success, the database held a finished production run and two recipes,
and both screens said "Module Not Enabled" — the warehouse profile the reset
applies does not offer the kitchen half, and the seeder writes it anyway. A
visitor met an empty state sitting on top of rows that already existed.

The invariant is one sentence: every module the seeder writes rows for is a
module the demo turns on. It is checked here rather than in the reset, because
the reset would have to run a database to find out, and the two lists are
constants — the mismatch is visible without either.
"""

from __future__ import annotations

from app.cli.commands_demo import DEMO_EXTRA_MODULES, DEMO_PROFILE_ID
from app.core.product_profiles import get_profile
from seed_demo_data import SEEDED_MODULES


def _demo_modules() -> set[str]:
    """What the demo runs whatever its model: the profile's list plus the extras.

    The AI modules (``DEMO_AI_MODULES``) seed no rows and are enabled only
    where the server's model serves them, so they are not part of this set.
    """
    profile = get_profile(DEMO_PROFILE_ID)
    assert profile is not None, (
        f'{DEMO_PROFILE_ID} is not a known product profile — the reset applies '
        f'it by name and would fail at run time.'
    )
    return set(profile.default_modules) | set(DEMO_EXTRA_MODULES)


class TestTheDemoEnablesWhatItSeeds:
    def test_every_seeded_module_is_enabled_on_the_demo(self):
        seeded_but_off = SEEDED_MODULES - _demo_modules()
        assert not seeded_but_off, (
            f'the demo seeds {sorted(seeded_but_off)} but does not enable '
            f'{"it" if len(seeded_but_off) == 1 else "them"}. The rows would be '
            f'written and the screen would say "Module Not Enabled" over the '
            f'top of them. Add the module to DEMO_EXTRA_MODULES, or stop '
            f'seeding it.'
        )

    def test_the_extras_are_the_ones_the_profile_does_not_already_offer(self):
        """Keep the extras list honest about why each entry is on it.

        An entry the profile already enables is not an extra; leaving it here
        suggests the demo needs it when the profile would have supplied it,
        and the next reader cannot tell which entries still carry weight.
        """
        profile = get_profile(DEMO_PROFILE_ID)
        assert profile is not None
        redundant = sorted(set(DEMO_EXTRA_MODULES) & set(profile.default_modules))
        assert not redundant, (
            f'{redundant} are already enabled by profile {DEMO_PROFILE_ID} — '
            f'drop them from DEMO_EXTRA_MODULES.'
        )
