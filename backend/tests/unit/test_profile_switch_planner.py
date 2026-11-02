"""Unit tests for app.services.profile_switch_planner.

Pure planner — no DB, no hooks, no modules — only deterministic algorithms
that turn a (current_modules, profile) pair into a `ProfileSwitchPlan`.

"""

from __future__ import annotations

from collections.abc import Collection

import pytest

from app.core._base_module import BaseModule
from app.core._module_declarations import ModuleMetadata
from app.core.product_profiles import ProductProfile
from app.services.profile_switch_planner import (
    ProfileSwitchError,
    build_profile_switch_plan,
)


def _make_module(name: str, requires: list[str] | None = None) -> BaseModule:
    """Build a tiny BaseModule stub for tests — no DB, no router."""

    class _Stub(BaseModule):
        @property
        def metadata(self) -> ModuleMetadata:
            return ModuleMetadata(
                name=name,
                display_name=name.title(),
                description=f'Stub {name}',
                icon='box',
                requires=list(requires or []),
            )

        def register_routes(self):
            raise NotImplementedError

    return _Stub()


_PROFILE_FACTORIES = {
    'food_home': lambda: ProductProfile(
        id='food_home',
        name='Food & Home',
        description='Cooking focus.',
        default_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'shopping_lists',
            'recipes',
            'stock_takes',
            'nutrition',
            'vision',
            'stats',
        ],
        seed_profile='food_home',
    ),
    'equipment_wms': lambda: ProductProfile(
        id='equipment_wms',
        name='Equipment & WMS',
        description='IT assets.',
        default_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
            'equipment',
            'stats',
        ],
        seed_profile='equipment_wms',
        module_config={
            'equipment': {'warranty_warning_days': 60},
        },
    ),
    'clean_core': lambda: ProductProfile(
        id='clean_core',
        name='Custom',
        description='Minimal.',
        default_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
        ],
        seed_profile='clean_core',
    ),
}


ALWAYS_ON: frozenset[str] = frozenset(
    {'core', 'items', 'locations', 'categories', 'stats'}
)


def _modules(*names: str) -> list[BaseModule]:
    return [_make_module(n) for n in names]


def _modules_with_deps(**deps: list[str]) -> list[BaseModule]:
    return [_make_module(name, requires=reqs) for name, reqs in deps.items()]


def _plan(
    *,
    current: Collection[str],
    profile: ProductProfile,
    modules: Collection[BaseModule],
    allowed: Collection[str] | None = None,
    source: ProductProfile | None = None,
):
    return build_profile_switch_plan(
        current_modules=current,
        profile=profile,
        modules=list(modules),
        always_on=ALWAYS_ON,
        allowed_modules=allowed,
        source_profile=source,
    )


@pytest.mark.unit
class TestProfileSwitchPlanBasic:
    """Basic enable/disable diff against the real built-in profiles."""

    def test_food_home_to_equipment_wms_disables_food_modules(self):
        food = _PROFILE_FACTORIES['food_home']()
        # Real registry modules — match the profile names.
        modules = _modules(
            'core',
            'items',
            'locations',
            'categories',
            'shopping_lists',
            'recipes',
            'stock_takes',
            'nutrition',
            'vision',
            'stats',
            'equipment',
        )
        plan = _plan(
            current=food.default_modules,
            profile=_PROFILE_FACTORIES['equipment_wms'](),
            modules=modules,
            source=food,
        )
        # food-only modules are directly disabled — they are part of the
        # source profile's defaults and absent from the target.
        assert sorted(plan.disable) == [
            'nutrition',
            'recipes',
            'shopping_lists',
            'vision',
        ]
        assert plan.cascade_disable == []
        assert 'equipment' in plan.enable
        # always-on must never be disabled
        for name in ALWAYS_ON:
            assert name not in plan.disable
            assert name not in plan.cascade_disable
            assert name in plan.final_enabled_modules

    def test_first_run_setup_enables_all_profile_modules(self):
        clean_core = _PROFILE_FACTORIES['clean_core']()
        modules = _modules(
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
            'stats',
        )
        plan = _plan(current=set(), profile=clean_core, modules=modules)
        assert plan.enable == ['stock_takes']
        assert plan.disable == []
        assert plan.cascade_disable == []
        assert plan.unchanged == []
        # final_enabled_modules includes profile defaults + always-on (stats).
        assert plan.final_enabled_modules == sorted(
            set(clean_core.default_modules) | ALWAYS_ON
        )

    def test_module_config_overwrite_lists_enabled_modules(self):
        plan = _plan(
            current=set(),
            profile=_PROFILE_FACTORIES['equipment_wms'](),
            modules=_modules(
                'core',
                'items',
                'locations',
                'categories',
                'stock_takes',
                'equipment',
                'stats',
            ),
        )
        assert plan.module_config_overwrite == ['equipment']

    def test_from_profile_id_is_passed_through(self):
        modules = _modules(
            'core', 'items', 'locations', 'categories', 'stock_takes', 'stats'
        )
        plan = _plan(
            current=['core', 'items', 'locations', 'categories', 'stats'],
            profile=_PROFILE_FACTORIES['clean_core'](),
            modules=modules,
        )
        assert plan.from_profile_id is None
        assert plan.to_profile_id == 'clean_core'


@pytest.mark.unit
class TestProfileSwitchCascade:
    """Reverse-dependency cascade behaviour."""

    def test_disabling_dependency_disables_dependent(self):
        # a depends on core
        # b depends on a
        # c depends on b
        modules = _modules_with_deps(
            core=[],
            a=['core'],
            b=['a'],
            c=['b'],
        )
        plan = _plan(
            current=['core', 'a', 'b', 'c'],
            profile=ProductProfile(
                id='only_core',
                name='Only Core',
                description='Just core.',
                default_modules=['core'],
                seed_profile='clean_core',
            ),
            modules=modules,
            source=ProductProfile(
                id='with_a',
                name='With A',
                description='Source profile that enabled a.',
                default_modules=['core', 'a'],
                seed_profile='clean_core',
            ),
        )
        assert set(plan.disable) == {'a'}
        assert set(plan.cascade_disable) == {'b', 'c'}
        # disable_all must include both
        assert set(plan.disable_all) == {'a', 'b', 'c'}
        # final_enabled_modules must not include any of them
        for name in ('a', 'b', 'c'):
            assert name not in plan.final_enabled_modules

    def test_target_keeps_dependency_for_dependent_module(self):
        # a depends on core
        # b depends on a
        # Profile asks for `core` and `b` without naming `a`. The planner
        # must keep `a` as a transitive dependency so `b` keeps working.
        modules = _modules_with_deps(core=[], a=['core'], b=['a'])
        plan = _plan(
            current=['core', 'a', 'b'],
            profile=ProductProfile(
                id='keeps_b',
                name='Keeps B',
                description='User wants to keep b but does not realise a is required.',
                default_modules=['core', 'b'],
                seed_profile='clean_core',
            ),
            modules=modules,
        )
        # final_enabled must include the transitive dependency 'a'.
        assert 'a' in plan.final_enabled_modules
        assert 'b' in plan.final_enabled_modules
        assert 'core' in plan.final_enabled_modules
        # Nothing is disabled — the closure added 'a' which was already on.
        assert plan.disable == []
        assert plan.cascade_disable == []

    def test_cascade_excludes_always_on(self):
        # a depends on core (always-on)
        modules = _modules_with_deps(core=[], a=['core'])
        plan = _plan(
            current=['core', 'a'],
            profile=ProductProfile(
                id='just_core',
                name='Only Core',
                description='Minimal.',
                default_modules=['core'],
                seed_profile='clean_core',
            ),
            modules=modules,
            source=ProductProfile(
                id='with_a',
                name='With A',
                description='Source profile that enabled a.',
                default_modules=['core', 'a'],
                seed_profile='clean_core',
            ),
        )
        # a must be disabled — the source profile owned it and the target
        # does not need it — while always-on core stays untouched.
        assert 'a' in plan.disable
        assert 'core' not in plan.disable
        assert 'core' not in plan.cascade_disable


@pytest.mark.unit
class TestProfileSwitchValidation:
    """Input validation and error mapping."""

    def test_unknown_profile_module_raises(self):
        modules = _modules('core', 'items', 'locations', 'categories', 'stats')
        with pytest.raises(ProfileSwitchError) as exc:
            _plan(
                current=['core'],
                profile=ProductProfile(
                    id='with_ghost',
                    name='Ghost',
                    description='References unknown module.',
                    default_modules=['core', 'definitely_not_registered'],
                    seed_profile='clean_core',
                ),
                modules=modules,
            )
        assert exc.value.code == 'unknown_module'
        assert 'definitely_not_registered' in exc.value.context['unknown_modules']

    def test_virtual_toggleable_module_not_treated_as_unknown(self):
        """Virtual toggleable modules (e.g. 'partners') have no
        ``BaseModule`` registration but are legitimate profile members. The
        planner must not reject them as 'unknown_module' and must carry them
        into the final enabled set so the apply path can persist them."""
        modules = _modules('core', 'items', 'locations', 'categories', 'stats')
        plan = _plan(
            current=['core'],
            profile=ProductProfile(
                id='with_virtual',
                name='Virtual',
                description='References a virtual module.',
                default_modules=['core', 'partners'],
                seed_profile='clean_core',
            ),
            modules=modules,
        )
        assert 'partners' in plan.final_enabled_modules
        assert 'partners' in plan.enable

    def test_premium_module_not_allowed(self):
        # premium_thing is a registered module but the org is not entitled to it.
        modules = _modules(
            'core', 'items', 'locations', 'categories', 'stats', 'premium_thing'
        )
        with pytest.raises(ProfileSwitchError) as exc:
            _plan(
                current=['core'],
                profile=ProductProfile(
                    id='pays_to_win',
                    name='Pays',
                    description='Needs premium.',
                    default_modules=['core', 'premium_thing'],
                    seed_profile='clean_core',
                ),
                modules=modules,
                # premium_thing is missing from the allow-list
                allowed=['core', 'items', 'locations', 'categories', 'stats'],
            )
        assert exc.value.code == 'module_not_allowed'

    def test_cycle_in_target_raises(self):
        # impossible: a requires b and b requires a
        modules = _modules_with_deps(
            core=[],
            a=['b'],
            b=['a'],
        )
        with pytest.raises(ProfileSwitchError) as exc:
            _plan(
                current=['core'],
                profile=ProductProfile(
                    id='cyclic',
                    name='Cyclic',
                    description='Cycle in target.',
                    default_modules=['core', 'a', 'b'],
                    seed_profile='clean_core',
                ),
                modules=modules,
            )
        assert exc.value.code == 'dependency_cycle'

    def test_dependency_closure_adds_missing_required_module(self):
        # profile requires 'downstream' which depends on 'core'
        # We add 'core' to the always-on list so it is implicit in target.
        modules = _modules_with_deps(core=[], downstream=['core'])
        plan = _plan(
            current=['core'],
            profile=ProductProfile(
                id='adds_downstream',
                name='Adds Downstream',
                description='Adds a downstream module.',
                default_modules=['downstream'],
                seed_profile='clean_core',
            ),
            modules=modules,
        )
        # Final enabled must include both downstream and core
        assert 'downstream' in plan.final_enabled_modules
        assert 'core' in plan.final_enabled_modules


@pytest.mark.unit
class TestProfileSwitchOrdering:
    """Deterministic ordering of enable/disable plans."""

    def test_enable_is_topological(self):
        # c depends on b, b depends on a, a depends on core
        modules = _modules_with_deps(
            core=[],
            a=['core'],
            b=['a'],
            c=['b'],
        )
        plan = _plan(
            current=['core'],
            profile=ProductProfile(
                id='chain',
                name='Chain',
                description='Chain of dependencies.',
                default_modules=['core', 'a', 'b', 'c'],
                seed_profile='clean_core',
            ),
            modules=modules,
        )
        # Enable order: core first, then a, b, c
        assert plan.enable == ['a', 'b', 'c']

    def test_disable_is_reverse_topological(self):
        # c depends on b, b depends on a, a depends on core
        modules = _modules_with_deps(
            core=[],
            a=['core'],
            b=['a'],
            c=['b'],
        )
        plan = _plan(
            current=['core', 'a', 'b', 'c'],
            profile=ProductProfile(
                id='only_core',
                name='Only Core',
                description='Drop everything but core.',
                default_modules=['core'],
                seed_profile='clean_core',
            ),
            modules=modules,
            source=ProductProfile(
                id='with_a',
                name='With A',
                description='Source profile that enabled a.',
                default_modules=['core', 'a'],
                seed_profile='clean_core',
            ),
        )
        # disable_all must disable c and b before a
        assert plan.disable_all.index('c') < plan.disable_all.index('a')
        assert plan.disable_all.index('b') < plan.disable_all.index('a')
        # The direct disable is 'a'; cascade is 'b', 'c'
        assert plan.disable == ['a']
        assert set(plan.cascade_disable) == {'b', 'c'}

    def test_planner_is_deterministic_for_same_input(self):
        modules = _modules(
            'core',
            'items',
            'locations',
            'categories',
            'shopping_lists',
            'recipes',
            'stock_takes',
            'nutrition',
            'vision',
            'stats',
            'equipment',
        )
        first = _plan(
            current=[
                'core',
                'items',
                'locations',
                'categories',
                'shopping_lists',
                'recipes',
                'stock_takes',
                'nutrition',
                'vision',
                'stats',
            ],
            profile=_PROFILE_FACTORIES['equipment_wms'](),
            modules=modules,
        )
        second = _plan(
            current=[
                'core',
                'items',
                'locations',
                'categories',
                'shopping_lists',
                'recipes',
                'stock_takes',
                'nutrition',
                'vision',
                'stats',
            ],
            profile=_PROFILE_FACTORIES['equipment_wms'](),
            modules=modules,
        )
        assert first == second


@pytest.mark.unit
class TestDeltaSemantics:
    """Delta semantics: a switch only
    disables modules owned by the source profile; manually enabled modules
    survive, and cascade is a true fixpoint over ``requires``."""

    def test_manual_modules_survive_switch(self):
        food = _PROFILE_FACTORIES['food_home']()
        modules = _modules_with_deps(
            core=[],
            items=[],
            storages=[],
            categories=[],
            stock_takes=[],
            stats=[],
            shopping_lists=[],
            recipes=[],
            nutrition=[],
            vision=[],
            equipment=[],
            api_keys=[],
            webhooks=[],
            printing=[],
            maker=['items', 'locations'],
        )
        plan = _plan(
            current=[
                *food.default_modules,
                'api_keys',
                'webhooks',
                'printing',
                'maker',
            ],
            profile=_PROFILE_FACTORIES['equipment_wms'](),
            modules=modules,
            source=food,
        )
        assert sorted(plan.disable) == [
            'nutrition',
            'recipes',
            'shopping_lists',
            'vision',
        ]
        assert plan.cascade_disable == []
        assert plan.warnings == []
        assert {'api_keys', 'webhooks', 'printing', 'maker'} <= set(plan.manual_kept)
        assert 'equipment' in plan.enable

    def test_true_cascade_when_dependent_requires_removed_module(self):
        food = _PROFILE_FACTORIES['food_home']()
        modules = _modules_with_deps(
            core=[],
            items=[],
            storages=[],
            categories=[],
            stock_takes=[],
            stats=[],
            shopping_lists=[],
            recipes=[],
            nutrition=[],
            vision=[],
            equipment=[],
            meal_photos=['vision'],
        )
        plan = _plan(
            current=[*food.default_modules, 'meal_photos'],
            profile=_PROFILE_FACTORIES['equipment_wms'](),
            modules=modules,
            source=food,
        )
        assert plan.cascade_disable == ['meal_photos']
        assert plan.warnings == [
            'meal_photos will be disabled because it requires vision.'
        ]
        assert 'meal_photos' not in plan.final_enabled_modules

    def test_cascade_chain(self):
        modules = _modules_with_deps(
            core=[],
            vision=[],
            b=['vision'],
            a=['b'],
        )
        plan = _plan(
            current=['core', 'vision', 'a', 'b'],
            profile=ProductProfile(
                id='only_core',
                name='Only Core',
                description='Drop vision.',
                default_modules=['core'],
                seed_profile='clean_core',
            ),
            modules=modules,
            source=ProductProfile(
                id='with_vision',
                name='With Vision',
                description='Source profile that enabled vision.',
                default_modules=['core', 'vision'],
                seed_profile='clean_core',
            ),
        )
        assert plan.disable == ['vision']
        assert set(plan.cascade_disable) == {'a', 'b'}
        # reverse-topological: dependents are disabled before their deps
        assert plan.disable_all.index('a') < plan.disable_all.index('b')
        assert plan.disable_all.index('b') < plan.disable_all.index('vision')

    def test_no_source_profile_is_additive(self):
        modules = _modules(
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
            'stats',
            'webhooks',
        )
        plan = _plan(
            current=['core', 'items', 'locations', 'categories', 'stats', 'webhooks'],
            profile=_PROFILE_FACTORIES['clean_core'](),
            modules=modules,
            source=None,
        )
        assert plan.disable == []
        assert plan.cascade_disable == []
        assert 'webhooks' in plan.manual_kept
        assert 'webhooks' in plan.final_enabled_modules

    def test_source_module_required_by_target_survives(self):
        modules = _modules_with_deps(
            core=[],
            warehouse=[],
            invoicing=['warehouse'],
        )
        plan = _plan(
            current=['core', 'warehouse'],
            profile=ProductProfile(
                id='with_invoicing',
                name='With Invoicing',
                description='Target needs documents transitively.',
                default_modules=['core', 'invoicing'],
                seed_profile='clean_core',
            ),
            modules=modules,
            source=ProductProfile(
                id='with_documents',
                name='With Documents',
                description='Source profile that enabled documents.',
                default_modules=['core', 'warehouse'],
                seed_profile='clean_core',
            ),
        )
        assert 'warehouse' not in plan.disable
        assert 'warehouse' not in plan.cascade_disable
        assert 'warehouse' in plan.final_enabled_modules

    def test_manual_kept_sorted_and_excludes_always_on(self):
        food = _PROFILE_FACTORIES['food_home']()
        modules = _modules(
            'core',
            'items',
            'locations',
            'categories',
            'stock_takes',
            'stats',
            'shopping_lists',
            'recipes',
            'nutrition',
            'vision',
            'zebra_mod',
            'alpha_mod',
        )
        plan = _plan(
            current=[*food.default_modules, 'zebra_mod', 'alpha_mod'],
            profile=_PROFILE_FACTORIES['clean_core'](),
            modules=modules,
            source=food,
        )
        assert plan.manual_kept == ['alpha_mod', 'zebra_mod']
        for name in ALWAYS_ON:
            assert name not in plan.manual_kept


@pytest.mark.unit
class TestLocationCodesOnASwitch:
    """A household's LOC- stickers are on its shelves: a switch to a business
    offers shelf codes and leaves the decision to the reader."""

    def _switch(self, source_id: str | None, target_id: str):
        from app.core.product_profiles import get_profile

        target = get_profile(target_id)
        source = get_profile(source_id) if source_id else None
        assert target is not None
        return _plan(
            current=list(source.default_modules if source else ALWAYS_ON),
            profile=target,
            modules=_modules(*target.default_modules, 'shopping_lists', 'recipes'),
            source=source,
        )

    @pytest.mark.parametrize('target', ['equipment_wms', 'clean_core'])
    def test_a_household_becoming_a_business_is_offered_renumbering(self, target):
        assert self._switch('food_home', target).offer_location_renumbering is True

    @pytest.mark.parametrize(
        ('source', 'target'),
        [
            ('equipment_wms', 'food_home'),
            ('clean_core', 'equipment_wms'),
            (None, 'equipment_wms'),
        ],
    )
    def test_no_other_switch_offers_it(self, source, target):
        assert self._switch(source, target).offer_location_renumbering is False
