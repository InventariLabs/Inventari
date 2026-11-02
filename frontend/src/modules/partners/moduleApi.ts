/**
 * What the partners module publishes to the modules that depend on it.
 *
 * `check:boundaries` counts every import of a module's internals as an edge;
 * this file is the one it lets through. A name is added here when a second
 * module needs it, and removing or renaming one is a breaking change for
 * them.
 */
// The inline "new partner" form a supplier or customer field opens, and the
// layer that keeps it above the dialog it was opened from.
export { PartnerInlineCreate } from "./components/PartnerInlineCreate";
export { usePartnerCreateLayer } from "./hooks/usePartnerCreateLayer";
// The banner a list shows while it is filtered to one partner.
export { PartnerFilterBanner } from "./components/PartnerFilterBanner";
