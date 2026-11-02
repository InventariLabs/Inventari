"""Recipe scraper primitives.

The only live scraper is the Jina+LLM one
(:func:`app.modules.recipes.scrapers.jina_llm.scrape_with_jina_llm_async`),
which is registry-backed. The historical tiered pipeline (community
recipe-scrapers library, then JSON-LD) had no live callers and was removed:
both tiers fetched by hostname after a validate-then-fetch guard, which is
exactly the DNS-rebinding window the cover fetcher had to stop having.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScrapedRecipe:
    """Normalised recipe data returned by the scraper pipeline."""

    title: str
    ingredients: list[str] = field(default_factory=list)
    instructions: str | None = None
    servings: int = 1
    image_url: str | None = None
    prep_time_minutes: int | None = None
    # Set to True when title/instructions were already translated by an LLM
    # (e.g. Jina+LLM path) so we skip the post-scraping translation step.
    translated: bool = False
    # BCP-47 language code detected from the source page (e.g. 'fr', 'de').
    # None means unknown. Used to skip translation when already in target lang.
    source_language: str | None = None
