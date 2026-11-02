# ADR-013: `success-*` Is a Separate Semantic Token; Profiles Repaint Only `primary-*`/`accent-*`

## Status

Accepted — 2026-08-14

## Context

The design system declared `primary-*` as the brand/action colour and
`accent-*` as the success/positive colour (`UI_GUIDELINES.md` §1.1). When
product profiles were introduced, the profile theme began overriding **both**
ramps with identical values — e.g. Equipment
& WMS sets `--color-primary-600` and `--color-accent-600` to the same
`37 99 235` (`backend/app/core/product_profiles.py`). That override is a
deliberate product decision: switching profiles must repaint the dominant
action colour across the whole app.

The side effect was unintended: the save button and the success confirmation
became indistinguishable. In the Equipment & WMS profile a success badge
(`bg-accent-50 text-accent-700`) renders blue and looks informational; green
stopped meaning "it worked".

## Decision

**Success gets its own semantic token ramp, `--color-success-*` (Tailwind
`success-*`), which no product profile overrides.**

- `primary-*` / `accent-*` — profile identity colours; profiles keep
  repainting them (the product decision stands).
- `success-*` — semantic "it worked / completed / available" signal; global
  emerald ramp for every profile, in both light and dark mode.
- The generic `Button` `success` variant and `Badge` `success` variant use
  `success-*`; module-level success indicators (condition chips, timeline
  badges, import/label success feedback) use `success-*` as well.
- `accent-*` remains allowed for profile-tinted *positive emphasis* that is
  not a status signal (e.g. progress bars, highlighted values).

The ramp values mirror the previous accent emerald values, so the Food & Home
profile renders exactly as before; only profiles whose accent was repainted
(Equipment & Warehouse today) change — deliberately.

## Alternatives considered

| Option | Why rejected |
|--------|--------------|
| Free `accent-*` back to the semantic role (profiles override only `primary-*`) | Silently reverts the documented product decision that a profile switch repaints the dominant action colour — including everywhere accent is still used decoratively. |
| Keep one ramp and accept the ambiguity | A success signal that changes hue with the profile is not a signal. |

## Consequences

- `UI_GUIDELINES.md` §1.1 documents three roles (action, identity/positive,
  success) instead of two.
- New profiles must not define `--color-success-*`; the profile theme
  injector keeps its current variable set.
- Existing decorative `accent-*` usages are left untouched unless they carry
  success semantics — re-pointing is incremental, not a migration.

## Risks

- **A third token about "green-ish positive" invites confusion.** Mitigation:
  `UI_GUIDELINES.md` §1.1 states the rule explicitly (`success-*` for status,
  `accent-*` for identity/emphasis) and the anti-patterns list bans raw
  `emerald-*`.
- **A profile could accidentally ship `--color-success-*`.** Mitigation:
  profile themes are defined in one file (`product_profiles.py`); review
  rejects any success override there.

## Implementation

- `frontend/src/index.css` — `--color-success-50..900` ramp (light + dark,
  values mirror the accent ramp so Food & Home is pixel-identical).
- `frontend/tailwind.config.js` — `success` colour mapped to the ramp.
- `frontend/src/components/ui/Button.tsx`, `Badge.tsx` — `success` variants
  re-pointed from `accent-*` to `success-*`.
- Equipment module success indicators re-pointed: condition chip
  (`checkinConditions.ts`, rendered by `CheckinModal.tsx`), timeline checkin badge (`AssetTimeline.tsx`), label
  assignment and import success feedback (`BatchLabelsSuccess.tsx`,
  `ImportEquipmentModal.tsx`).
- Purchase-order status badges inherit the fix through `Badge`'s `success`
  variant (`STATUS_COLORS` in `purchase_orders/lib/statusColors.ts`).

## References

- `frontend/UI_GUIDELINES.md` §1.1 (colour roles and the success rule).
- `backend/app/core/product_profiles.py` — profile theme ramps and the
  rationale comment.
