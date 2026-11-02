# Purpose cards

A purpose card answers the one question a screen cannot answer about itself: **whose job is this,
and where does it end.**

Reviews of this app kept producing carefully labelled screens full of fields that should not have
been on them, because the reviewer inferred the goal from the fields in front of them and then
confirmed that the fields could be filled in. The card is the outside source that makes the other
question askable: not "is this field explained" but "does this field belong to the person doing
this job".

These cards are the module-purpose reference: read the relevant card before reviewing or changing
a module's screens or flows. Written by whoever owns the module.

## Where a card lives

| For | Path | Matching code |
|---|---|---|
| A module | `docs/purpose/<module>.md` | `backend/app/modules/<module>/` |
| A Core area | `docs/purpose/core-<area>.md` | `frontend/src/modules/<area>/` |

Every backend module (15 under `backend/app/modules/`) has a card. The Core areas that have one
are announcements, inventory, launcher, onboarding, partners, settings and spaces. The one
directory under `frontend/src/modules/` without a card is `shared`: it holds shared components and
hooks, not a screen or a workflow of its own (see `docs/FOCUS_MODE.md`).

## The shape

Seven headings, in this order, and nothing else. Short is the point — a card nobody finishes
reading is a card nobody reads before a review.

- **Job** — one sentence, in the words of the person doing it, never in the words of the app.
  "Know what I have and whether it is still good", not "manage inventory records".
- **Whose job** — who actually does it, and which roles touch it. If everybody touches it, say so;
  if only an administrator does, that alone answers half the belonging questions.
- **Inside the boundary** — what this area decides.
- **Outside the boundary** — what it deliberately leaves to someone else, naming who.
- **Own concepts / Borrowed** — which nouns belong to this area and which it takes from the Core or
  another module. A screen putting a borrowed noun in front of the user has to justify it twice.
- **Deliberately not done** — the part that earns the card. Without it every absence looks like a
  gap, and a review turns into a feature list.
- **Switched off** — what a user loses, and what still has to work, when the module is disabled.
  Modules must degrade, not crash (`backend/AGENTS.md`, Cross-Module API Contracts, rule 3).

## Rules

- The card states what the area is **meant** to be, not an inventory of what happens to be built.
  Where the two differ, the difference is a finding — that is the card doing its job.
- **Deliberately not done is not a backlog.** It is what this area will not do even when asked. An
  item that is merely unbuilt belongs in the backlog, not here.
- A card that cannot fill "Deliberately not done" has not found its boundary yet. Say that in the
  card rather than leaving the heading empty.
- Change the card in the same change that moves the boundary. A card that lags is worse than no
  card, because a review will trust it.
