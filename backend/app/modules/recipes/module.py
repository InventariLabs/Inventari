"""Recipes module — recipe management with ingredient availability checking."""

from typing import Any

from app.core.logging import get_logger
from app.core.modules import BaseModule, ModuleMetadata
from app.core.public_api import core_api
from app.core.public_api.llm import LlmCapability
from app.modules.recipes._probe import probe as text_parse_probe

log = get_logger(__name__)

# Register recipes' AI purposes at module-load time so the Core resolver
# can bind each to its own connection slot:
#   settings.ai.defaults[<purpose key>]
# (choices made on the module's single legacy slot keep serving until
# re-bound — see binding_from_settings). The text purpose carries a contract
# probe, so testing a text connection asks it to parse ingredient lines
# rather than only list its models.
core_api.llm.register_purpose(
    key='recipes.text_parse',
    capability=LlmCapability.TEXT,
    label_key='recipes:ai.purposeLabel',
    description_key='recipes:ai.purposeDesc',
    owner_module='recipes',
    probe=text_parse_probe,
)

# The page reader behind importing a recipe from a URL. Not an LLM: the
# connection carries the reader's key, and the import pipeline fetches
# with it itself (scrapers/jina_llm._fetch_via_jina) — the resolver hands
# out the row, never a client.
core_api.llm.register_purpose(
    key='recipes.url_fetch',
    capability=LlmCapability.URL_FETCH,
    label_key='recipes:ai.urlFetchPurposeLabel',
    description_key='recipes:ai.urlFetchPurposeDesc',
    owner_module='recipes',
)


class RecipesModule(BaseModule):
    focus_background_modules = ('shopping_lists',)

    def __init__(self) -> None:
        self._metadata = ModuleMetadata(
            name='recipes',
            version='0.8.0',
            display_name='Recipes',
            description='Recipe management with ingredient availability checking and scan-to-pick mode.',
            icon='chef-hat',
            category='business',
            module_type='official',
            requires=['items'],
            # A picking shortfall can be pushed onto a shopping list, but the
            # module cooks without one — the integration degrades gracefully
            # through the shopping list module's public API, which no-ops when
            # that module is off. Declared so the store can say the companion
            # exists, not so enabling can be refused.
            optional_requires=['shopping_lists'],
        )

    @property
    def metadata(self) -> ModuleMetadata:
        return self._metadata

    def register_routes(self) -> Any:
        from app.modules.recipes.router import router

        return router

    def register_contributions(self) -> None:
        from typing import cast

        from app.core.contributions import BaseContribution, contribution_registry
        from app.core.template_ranking import register_template_ranker

        from .recipes_api import rank_templates_by_recipe_usage
        from .resolvers import RecipeCoverResolver

        # Core can list templates but cannot order them by recipe usage — that
        # count lives in this module's RecipeIngredient table. Hand Core the
        # ranker here instead of letting it import recipes.
        register_template_ranker(rank_templates_by_recipe_usage)

        contribution_registry.register(
            'upload_path_resolvers',
            cast(BaseContribution, RecipeCoverResolver()),
        )

    async def on_startup_async(self, context: Any = None) -> None:
        """Declare event payload contracts, then seed defaults and conversions."""
        from app.core.contracts.events import (
            RecipeCreatedPayload,
            RecipeMealPlanGeneratedPayload,
            RecipePickingCompletedPayload,
        )
        from app.core.public_api import core_api

        # Ownership claims ahead of the planned move of these classes out of
        # the core table — no-ops while the core table still lists them.
        core_api.events.register_payload('recipe.created', RecipeCreatedPayload)
        core_api.events.register_payload(
            'recipe.picking_completed', RecipePickingCompletedPayload
        )
        core_api.events.register_payload(
            'recipe.meal_plan_generated', RecipeMealPlanGeneratedPayload
        )

        try:
            from app.modules.recipes._defaults_seeding import (
                deduplicate_defaults,
                seed_system_defaults,
            )
            from app.modules.recipes.migration import (
                migrate_all_orgs_recipes_jina_key_async,
            )
            from app.modules.recipes.unit_conversion_service import (
                seed_system_conversions,
            )

            async with context.global_session() as db:
                deduped = await deduplicate_defaults(db)
                if deduped:
                    log.info(
                        'RecipesModule: removed %d duplicate ingredient defaults',
                        deduped,
                    )
                inserted = await seed_system_defaults(db)
                if inserted:
                    log.info(
                        'RecipesModule: seeded %d ingredient nutrition defaults',
                        inserted,
                    )
                conversions = await seed_system_conversions(db)
                if conversions:
                    log.info(
                        'RecipesModule: seeded %d system unit conversions',
                        conversions,
                    )
                # This session is the seeders' own: nothing above them
                # commits, so the unit of work closes here.
                await db.commit()
                await migrate_all_orgs_recipes_jina_key_async(db)
        except Exception:  # seeding must not stop startup
            log.exception('RecipesModule: failed to seed ingredient nutrition defaults')

    def get_settings_schema(self) -> dict[str, Any] | None:
        return {
            'type': 'object',
            'properties': {
                # No reader key here: a credential for an external provider
                # belongs to the AI Connections registry, where the
                # administrator rotates and tests it, and the screen a cook
                # opens must not ask them what a reader or a rate limit is.
                # Controls whether the recipe cost
                # calculator is enabled. Home users may not care about the
                # EUR/USD price on each recipe; business kitchens do. Profiles
                # override the default via `ProductProfile.module_config`.
                'enable_cost_calculation': {
                    'type': 'boolean',
                    'default': True,
                    'title': 'Enable cost calculation',
                    'title_key': 'recipes:settings.enableCostCalculation',
                    'description_key': 'recipes:settings.enableCostCalculationDescription',
                    'description': (
                        'Show the per-recipe cost breakdown in the recipe view. '
                        'Disable for home setups where recipe cost is irrelevant.'
                    ),
                },
                # Audit-trail RW document for completed picking sessions.
                # Off by default — home behavior is unchanged. Business
                # kitchens enable it so every production run lands in the
                # document register (subject to approvals/accounting exports).
                'register_production_as_document': {
                    'type': 'boolean',
                    'default': False,
                    # The document register belongs to the warehouse; an
                    # organization without it is not offered the option.
                    'requires_modules': ['warehouse'],
                    'title': 'Register production as internal issue documents',
                    'title_key': 'recipes:settings.registerProductionAsDocument',
                    'description_key': 'recipes:settings.registerProductionAsDocumentDescription',
                    'description': (
                        'Create an audit-trail internal issue '
                        'document for every completed picking session. '
                        'Requires the warehouse module.'
                    ),
                },
            },
            'additionalProperties': False,
        }

    def get_default_settings(self) -> dict[str, Any]:
        return {
            'enable_cost_calculation': True,
            'register_production_as_document': False,
        }
