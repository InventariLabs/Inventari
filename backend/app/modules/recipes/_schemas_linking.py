"""Schemas for the global ingredient-linking screen.

One view of every recipe ingredient the organization has not linked to a
product (``template_id IS NULL``), the match proposals the LLM returns for
them, and the bulk write that applies the approved subset.
"""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import PaginatedResponse


class UnlinkedIngredient(BaseModel):
    """One unlinked ingredient, with enough context to recognise it."""

    id: UUID
    recipe_id: UUID
    recipe_name: str
    name: str
    #: What the matcher reads — the group name when the parser stored one,
    #: the display name otherwise. Same choice the import pipeline makes.
    match_name: str
    quantity: Decimal
    uom_symbol: str | None = None


class UnlinkedIngredientsResponse(PaginatedResponse[UnlinkedIngredient]):
    #: Every ingredient of the organization's recipes, linked or not — what
    #: tells "everything is linked" apart from "there are no ingredients".
    ingredient_total: int = 0


class IngredientMatchProposal(BaseModel):
    ingredient_id: UUID
    template_id: UUID
    template_name: str


class IngredientMatchProposalsResponse(BaseModel):
    #: Only the rows a product was proposed for. Everything else in the
    #: backlog stays for a manual link or the next pass.
    proposals: list[IngredientMatchProposal]
    #: How many unlinked ingredients the matcher looked at.
    considered: int


class IngredientTemplateLink(BaseModel):
    ingredient_id: UUID
    template_id: UUID


class BulkLinkIngredientsRequest(BaseModel):
    links: list[IngredientTemplateLink] = Field(min_length=1, max_length=500)


class BulkLinkIngredientsResponse(BaseModel):
    linked: int
    #: Recipes the write touched, so a caller can refresh exactly those
    #: detail caches instead of guessing.
    recipe_ids: list[UUID]
