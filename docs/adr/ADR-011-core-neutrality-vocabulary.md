# ADR-011: Core Neutrality Vocabulary (USED/DISPOSED over CONSUMED/DISCARDED)

## Status

Accepted — 2026-07-12; amended 2026-10-23. The amendment (see *Update
2026-10-23* below) removed the legacy values from the stored data, so the
alias enum members, the dual-vocabulary read path and the event shim this
record describes are history: one vocabulary, `USED` / `DISPOSED`, is stored
and read.

## Context

Inventari originated as a **food inventory app** (fridge/pantry tracking). Its
early vocabulary reflected that: an item you eat was `CONSUMED`; an item you
threw away was `DISCARDED`. These became enum values in `ItemAction` and were
written to `ItemHistory` rows, event names (`ITEM_CONSUMED`), translations, and
analytics queries.

As the project expanded to IT equipment and warehouse verticals, this
vocabulary became a **multi-vertical correctness problem**:

- An ITAM user does not "consume" a laptop — they **use** it. A laptop is not
  "discarded" — it is **disposed of** (often via certified e-waste).
- A warehouse does not "consume" a pallet.
- The food terms read as unprofessional or confusing in non-food contexts.

This is the vocabulary half of Core Neutrality (see
[ADR-009](ADR-009-core-neutrality-and-3-vertical-test.md)) — schema neutrality
keeps the *fields* neutral; vocabulary neutrality keeps the *terms* neutral.

The constraint that made this non-trivial: **`CONSUMED` and `DISCARDED` were
already stored in millions of `ItemHistory` rows and hardcoded in analytics
queries.** A naive rename (`s/CONSUMED/USED/`) would break stored history and
every consumer reading it.

## Decision

**Introduce neutral enum values (`USED`, `DISPOSED`) as the preferred terms for new writes, keep the food-specific values (`CONSUMED`, `DISCARDED`) as deprecated backward-compat aliases, and read-path-match both via canonical tuples. No data migration rewrites historical rows.**

### The enum

`backend/app/models/item_history.py:11-36`:

```python
class ItemAction(str, Enum):
    ...
    MOVED = 'MOVED'           # Deprecated alias: use TRANSFERRED for new verticals
    CONSUMED = 'CONSUMED'     # Deprecated alias: use USED for new verticals
    USED = 'USED'             # Neutral — preferred over CONSUMED for new writes
    DISCARDED = 'DISCARDED'   # Deprecated alias: use DISPOSED for new verticals
    DISPOSED = 'DISPOSED'     # Neutral — preferred over DISCARDED for new writes
```

Canonical groupings (line 29-36) so a single query matches both vocabularies:
```python
CONSUMPTION_ACTIONS = (ItemAction.CONSUMED.value, ItemAction.USED.value)
DISPOSAL_ACTIONS   = (ItemAction.DISCARDED.value, ItemAction.DISPOSED.value)
```

### Writes emit neutral terms; reads match both

- **New writes** (`backend/app/services/items/move_service.py`):
  `consume_item` emits `ItemAction.USED` + `SystemEvent.ITEM_USED`;
  `discard_item` emits `ItemAction.DISPOSED` + `SystemEvent.ITEM_DISPOSED`.
- **Reads** use the canonical tuples so historical `CONSUMED` rows still appear
  in analytics: e.g. `ItemHistory.action.in_(['CONSUMED', 'DISCARDED', 'USED',
  'DISPOSED'])` (`modules/stats/_analytics_queries.py:60`,
  `services/analytics/rotation.py:92`, `shopping_suggestions_service.py:175`).
- **Event back-compat shim** (`move_service.py:28-29`): maps
  `ITEM_USED → ITEM_CONSUMED` and `ITEM_DISPOSED → ITEM_DISCARDED` so legacy
  event subscribers keep firing — the neutral event is emitted, then the legacy
  one, so nothing breaks during the transition.
  - *Update 2026-09-21:* the shim and the two alias names themselves were
    removed before the repository went public — the only databases that held
    subscriptions by the old names were disposable dev/demo data, so the
    window this ADR planned was never needed. `CONSUMED`/`DISCARDED` remain
    readable as historical `ItemHistory` values; only the event names are
    gone.

*Update 2026-10-23:* before the first public release the legacy values left
  the stored data as well. No published database exists yet; the owner's
  instance and the demo are reached by migration `legacyvals01`, which
  rewrites `CONSUMED` → `USED` and `DISCARDED` → `DISPOSED` in
  `items.deletion_reason`, `item_history.action` and
  `stock_valuation_layers.reason` (the migration now sits in
  `backend/migrations/versions_archive/`, behind the flattened baseline). The
  alias enum members go with it, and the canonical tuples
  `CONSUMPTION_ACTIONS` / `DISPOSAL_ACTIONS` keep their names with one value
  each: one vocabulary is stored and read from now on. The audit-immutability concern below is about a published
  history, and there is none before the release.

### No data migration

*Superseded before the first release — see the 2026-10-23 update above. The
reasons below apply to a published history; the pre-release database was
rewritten instead.*

Deliberately, **no migration rewrites `CONSUMED`/`DISCARDED` rows to
`USED`/`DISPOSED`**. Reasons:
1. Stored history is immutable audit data — rewriting it risks losing the
   original semantics.
2. A rewrite would be a large, risky UPDATE across every org's history table.
3. The read-path tuple matching makes a rewrite unnecessary for correctness.

Historical rows keep their legacy values; only **new** writes use the neutral
terms. Over time the legacy values age out naturally.

### Why vocabulary matters beyond aesthetics

- **i18n.** Core enforces 5-language support (see ADR-010 condition 5). A
  food-biased enum value becomes a food-biased translation in every language
  for every vertical. `CONSUMED` → "spożyto" (PL) makes no sense for an IT
  asset; `USED` → "użyto" works for both.
- **First impressions.** A warehouse manager evaluating Inventari sees enum
  values in exports/API responses. `CONSUMED` signals "this is a food app";
  `USED` signals "this is a neutral tool."
- **Mental model alignment.** Non-food users map their domain onto the system
  faster when the terms match their vocabulary.

## Consequences

### Positive

- **Multi-vertical correctness.** New verticals see neutral terms in new data;
  no domain imposed.
- **Zero-risk migration.** No data rewrite; back-compat aliases + read-path
  tuples mean nothing breaks.
- **Forward path.** The legacy values will naturally age out; a future major
  version can deprecate them fully once analytics confirm low prevalence.

### Negative

- **Dual vocabulary in the codebase.** Readers must understand both terms and
  the alias map. Mitigated by the canonical tuples (one idiom to learn).
- **Storage retains legacy values indefinitely.** Not a correctness issue, but
  purists may object. The trade-off (audit immutability) is worth it.

## Alternatives considered

| Approach | Multi-vertical fit | Backward compat | Verdict |
|----------|-------------------|-----------------|---------|
| **Keep `CONSUMED`/`DISCARDED` only** | Poor (food-imposed) | Full | Rejected — fails neutrality. |
| **Big-bang rename + data migration** | Good | Risky (rewrites audit data) | Rejected — immutability/size risk. |
| **Neutral terms + aliases + tuple reads (chosen)** | Good | Full | **Chosen.** Best fit, zero migration risk. |
| **Per-vertical vocabulary (each module defines its own)** | Perfect locally | Fragmented globally | Rejected — analytics can't aggregate; loses the single-source enum. |

## Implementation

As amended on 2026-10-23:

- Enum: `ItemAction` in `backend/app/core/contracts/_system_dtos.py`,
  re-exported with the one-value canonical tuples by
  `backend/app/models/item_history.py`.
- Neutral writes: `backend/app/services/items/move_service.py`
  (`consume_item`, `discard_item`, `_reduce_quantity`).
- Event shim: removed (*Update 2026-09-21*).
- Read-path tuple matching: `modules/stats/_analytics_queries.py`,
  `services/analytics/rotation.py`, `shopping_suggestions_service.py`.
- Rule text: `backend/AGENTS.md` §4, "Neutral defaults and vocabulary".

## References

- `backend/AGENTS.md` §4, "Neutral defaults and vocabulary" — the rule text.
- [ADR-009](ADR-009-core-neutrality-and-3-vertical-test.md) — the schema half
  of Core Neutrality (this ADR is the vocabulary half).
- The neutrality migration (Phases 2/3 cover `freeze_date`/`production_date`
  schema moves, see ADR-009).
