# ADR-009: Core Neutrality & the 3-Vertical Test

## Status

Accepted — 2026-07-12

## Context

Inventari's Core is explicitly **domain-neutral**: it must serve food tracking,
IT asset management, warehouse operations, pharma, libraries, and future
verticals without favoring any of them. Neutrality is what keeps one codebase
reusable across all of these verticals instead of fragmenting into per-domain
variants, and the 3-vertical rule below is its enforcement mechanism.

The constant threat is **domain drift**: a well-meaning contributor adds a
food-specific field (`freeze_date`), a food-specific default
(`behavior_mode='EXPIRY'`), or a food-specific example (`Pantry`) to Core
because it solves their immediate problem. Each addition seems harmless; in
aggregate they turn the "neutral core" into a "food app with bolted-on
verticals." Once `Pantry` is a hardcoded default, every ITAM user fights it.

The question: **how do we decide, mechanically, what belongs in Core vs. a
module?** "Use judgment" is not an answer — judgment fails under deadline
pressure and diverges across contributors.

## Decision

**Every proposed Core addition must pass the 3-Vertical Test: it must be needed by at least 3 distinct verticals. If it does not, it belongs in a module or in `meta_data[<namespace>]`. The test is documented in `AGENTS.md` and enforced by convention (review gate) plus the vocabulary/defaults rules.**

### The test (exact form)

> _Would this concept be needed by at least 3 different verticals (e.g., food,
> equipment, library)?_
> **If NO → it belongs in a module, not in Core.**
> — `AGENTS.md` §4

### Application — what passed and what failed

| Concept                       | Verticals needing it                          | Verdict        | Where it lives                                                                                                                                                      |
| ----------------------------- | --------------------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `barcode`                     | food, pharma, electronics, warehouse, library | ✅ Passes      | Core (`Item`)                                                                                                                                                       |
| `expiry_date`                 | food, pharma, cosmetics/chemicals             | ✅ Passes (3+) | Core (`Item`, indexed) — (today: a record is one batch of one owner on one shelf, ADR-022, so its expiry is that batch's). |
| `serial_number`               | pharma, electronics, warehouse (GS1/UDI)      | ✅ Passes      | Core (`Item`, indexed, partial unique)                                                                                                                              |
| `freeze_date`                 | only food (freezing is a kitchen concept)     | ❌ Fails       | Migrated OUT → `meta_data['food']['freeze_date']`                                                                                                                   |
| `production_date`             | only manufacturing                            | ❌ Fails       | Migrated OUT → `meta_data['manufacturing']['production_date']`                                                                                                      |
| `warranty_until`              | IT/equipment (and some automotive) — not 3    | ❌ Fails       | Equipment module                                                                                                                                                    |
| `assigned_to`                 | IT/equipment only                             | ❌ Fails       | Equipment module                                                                                                                                                    |
| `lot_number` (scalar on Item) | fails for a different reason                  | ❌ Reversed    | `Item:lot` is 1:N — a scalar cannot represent the truth; lots live on `Item.lot_id → StockLot` (today; the `StockQuant` table is gone, ADR-022).                                                               |

### The two accepted exceptions

`expiry_date` and `serial_number` are the **only** domain-leaning fields
permitted on Core `Item`. Both are documented as exceptions in `AGENTS.md` with
their 3-vertical justification. **They are precedents that require equivalent
justification to extend — not a license to add similar fields.** Each was added
after a dedicated analysis that spelled out the verticals
and the compliance driver (GS1/WMS, indexed FEFO).

> ⚠️ The original `serial_number` proposal also included adding a scalar
> `lot_number` to Item; that half was **reversed** because a single Item
> can span multiple lots (1:N). Do not cite that proposal as justification for a
> scalar lot field — it is superseded by the `StockLot` model (the `StockQuant` table
> is gone, ADR-022).

### How to extend Core _without_ violating neutrality

When a vertical needs a domain-specific field, use one of these patterns
instead of adding a Core column:

1. **`meta_data[<namespace>]`** — JSONB on the existing Core entity, namespaced:
   ```python
   item.meta_data['nutrition'] = {'calories': 250}     # food module
   item.meta_data['equipment'] = {'serial_number': ...} # equipment module
   ```
   Namespacing prevents modules polluting each other's keys.
2. **Module-local tables** — a dedicated table in the module's own migration,
   FK'd to the Core entity. Heavier, but typed and queryable.
3. **`field_definitions` on Categories** — admin-defined custom fields per
   category, rendered dynamically. No schema change.

### Companion rules (also in `AGENTS.md` §4)

- **No domain columns in Core models** (`warranty_until`, `assigned_to`,
  `equipment_status`...).
- **`category_type` is gone** — the old food column was dropped before the
  first release; categories carry `context_tag` (who owns them) and
  `group_label` (how the organisation groups them).
- **Neutral defaults** — `behavior_mode` must not default to `'EXPIRY'`;
  fallbacks must not assume `'PANTRY'`.
- **Neutral vocabulary** — `USED`/`DISPOSED` are the only stored action and
  reason values; the food-era `CONSUMED`/`DISCARDED` were rewritten before the
  first release (see [ADR-011](ADR-011-core-neutrality-vocabulary.md)).
- **Neutral examples in comments/docstrings** — use `Cold Storage`, `Shelf A`,
  `Receiving`, `Quarantine`; never `Fridge`, `Pantry`, `Kitchen`.

## Consequences

### Positive

- **Neutrality holds.** Core stays genuinely multi-vertical; each new vertical
  is a module, not a fork.
- **Mechanical decision.** "Passes 3-vertical?" is answerable in a PR review
  without bikeshedding.
- **Reversible extensions.** `meta_data` and module tables can evolve without
  Core migrations.

### Negative

- **Friction for the food vertical (the project's origin).** Food-specific
  conveniences that "feel obvious" are rejected from Core. This is by design
  but requires patience.
- **Exceptions can be cited out of context.** "But `expiry_date` is in Core!"
  is the classic argument for adding `freeze_date`. The response is the test,
  not the precedent.

## Alternatives considered

| Approach                               | Neutrality          | Contributor friction                                                          | Verdict                                                                           |
| -------------------------------------- | ------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **3-Vertical Test (chosen)**           | Strong (mechanical) | Medium (must justify)                                                         | **Chosen.** Objective enough to enforce in review.                                |
| **"No domain fields in Core, period"** | Strongest           | High (rejects `expiry_date`/`serial_number` that 3+ verticals genuinely need) | Rejected — too pure; indexed FEFO and GS1 compliance demand those two exceptions. |
| **Per-vertical Core forks**            | None                | Low locally, catastrophic globally                                            | Rejected — defeats the entire project premise.                                    |
| **Let it drift, fix later**            | None                | Low now                                                                       | Rejected — "later" never comes; drift compounds.                                  |

## Implementation

- Rule text: `AGENTS.md` §4 "Core Neutrality (Domain-Agnostic Core)".
- Accepted exceptions: `Item.expiry_date` and `Item.serial_number`
  (`models/item.py`).
- Migrated-out precedent: `migrations/versions_archive/movefreezedate01_*.py`,
  `migrations/versions_archive/moveproddate01_*.py`; legacy compat shim `services/items/_date_meta.py`.
- Enforcement: PR review (CODEOWNERS on `backend/app/models/` and
  `backend/app/core/`).

## References

- `AGENTS.md` §4 "Core Neutrality (Domain-Agnostic Core)" — the authoritative
  rule text.
- [ADR-004](ADR-004-stockquant-source-of-truth.md) — why `expiry_date` is a
  denormalized cache aligned with `StockLot`.
- [ADR-011](ADR-011-core-neutrality-vocabulary.md) — the vocabulary half of
  neutrality (enum values, not schema).
- The migration that moved `freeze_date`/`production_date` out of Core
  (historical context).
