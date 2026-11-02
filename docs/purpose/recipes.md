# Recipes

## Job
"Keep the recipes I actually cook, and tell me whether I could cook one right now with what is in
the house."

## Whose job
Whoever cooks. Writing a recipe and cooking it are separate permissions on purpose: cooking takes
things out of stock, writing does not.

## Inside the boundary
The recipe itself — ingredients, quantities, portions, steps — the match between its ingredients and
what is actually in stock, and the consumption that happens when it is cooked. Around it, three
estimates read off the ingredients: what a portion roughly contains, what the recipe roughly costs
(from the stock's own cost, then supplier offers, then a price typed on the line), and which EU
allergens its ingredients carry, guessed from their names and correctable by hand. For an
ingredient line with no linked product, generic per-ingredient nutrition values — shipped ones,
and an organization's own overrides. Around the recipes too: meal plans for dated days, whose
missing ingredients go to a shopping list and whose suggestions come from what is in stock;
collections; recipes imported from a web page, where an AI model reads the page and each import
counts against the organization's monthly AI budget; and export.

## Outside the boundary
- Making something *to stock*, with a cost attached → **maker**
- What the label on a specific product says → that product's nutrition, filled by **nutrition**
- Buying what is missing → **shopping_lists**
- Stock and units → **Core — Inventory**

## Own concepts / Borrowed
**Own:** Recipe, ingredient line, portion, cooking session, the stock-match result, generic
ingredient nutrition values, the ingredient's allergens, meal plan and its entries, collection.
**Borrowed:** ProductTemplate, Item, UoM (Inventory) — and the unit bridge that lets a
recipe asking for grams meet a product counted in pieces; the shopping list that missing
ingredients are written to (shopping_lists); the AI connection and its usage budget (Core), which
a web import and an ingredient parse draw on.

## Deliberately not done
- **No second source of truth for a product.** The generic values answer for an ingredient
  named only by its name; a linked product's own figures win and are never overwritten by them.
- **No production costing.** The cost is an estimate for the person cooking; booking what a batch
  was worth is **maker**'s.
- **No sharing or community.** Recipes belong to the workspace that wrote them; a cook may rate
  how a cooking went, for the workspace alone.
- **No dietary advice.** Allergens are labelled; nobody is told what they may or should eat.

## Switched off
Nothing in stock changes. Anything elsewhere that offers "cook this" or shows what a recipe needs
must disappear rather than fail.
