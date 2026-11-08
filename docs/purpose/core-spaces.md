# Core — Spaces (storage locations)

## Job
"Say where a thing is, in the words of my own building."

## Whose job
Whoever puts things away and whoever goes looking for them. The layout is usually drawn once, by
whoever set the workspace up, but it is not an administrator's alone: adding or renaming a shelf is
part of putting stock away, so an ordinary member (the built-in User and Manager roles) may write
locations too, and only a viewer, or a custom role without the locations write permission, just
picks a place from it.

That split is the sharpest question on any Spaces screen: **is this something the person naming a
shelf decides, or something the person who designed the layout decided once?**

## Inside the boundary
The tree of locations — any depth, described only by each node's parent (ADR-018) — the name and
short code that identify each node, the full path that tells two identically named shelves apart,
and what kind of place it is: the storage type, and the behaviour that follows from it (does this
place watch expiry, does it freeze what is in it).

## Outside the boundary
- What stands in a place, and how much → **Core — Inventory**
- Moving things between places as a recorded event → **warehouse**
- Counting what is actually there → **stock_takes**
- Deciding where a thing should go → **warehouse** (putaway rules)

## Own concepts / Borrowed
**Own:** StorageLocation, StorageType, behaviour mode, parent, short code, virtual location.
**Borrowed:** nothing. Modules attach themselves to locations by tagging them, never by adding
columns. (The table still carries `warehouse_config`, left from an early warehouse design; no code writes
it. It is read only into the core `StorageDTO` that modules receive from the Core API, and the
storage screens do not expose it.)

## Deliberately not done
- **No capacity, no slotting, no floor plan.** The tree *names* places; it does not model them. No
  dimensions, no weight limits, no map.
- **No routing vocabulary in front of the ordinary user.** Virtual locations exist so that using
  something up, losing it or correcting a count, and consuming it in production **moves** it
  somewhere instead of deleting it, and the history survives. They are destinations for an action,
  not a property the person naming a shelf is expected to choose.
- **No per-place permissions.** Access is decided by role and module, not by shelf.

## Switched off
Cannot be. Everything that has a quantity has a place.
