/**
 * Why a general (non-module) location picker has nothing to offer.
 *
 *  - `module-data-hidden` — locations exist that this picker would offer,
 *     but the organization keeps module-owned data out of its general lists,
 *     so they are hidden. Turning that setting on reveals them: advice that
 *     works.
 *
 *  - `nothing-to-offer` — there is no location this picker may offer at all.
 *     The only rows the organization holds are the virtual counterparts
 *     (move targets, not places goods may land) or archived locations.
 *     Pointing the reader at the setting here would send them to a switch
 *     that reveals nothing.
 */
export type LocationPickerEmptyReason =
  "module-data-hidden" | "nothing-to-offer";

/**
 * What a picker is for — the flow behind it decides what it may offer.
 *
 *  - `general` — a list, a filter, a management screen. What the
 *     organization keeps out of its general lists stays out (the
 *     `show_module_data` policy), and an empty picker may name that policy
 *     as the way back.
 *
 *  - `stock` — a flow that puts goods down or takes them out: the product
 *     form, receipts, issues, moves, production. A place a vertical module
 *     owns is never offered here — a server rack is not where warehouse
 *     stock stands, whatever the general lists mix — so what such a flow is
 *     offered is what may hold stock, plus the place a record already stands
 *     in (the place the form holds, named by id), so opening a record never
 *     blanks its own.
 */
export type LocationPickerPurpose = "general" | "stock";
