import type { components, WithServerDefaults } from "@/module-sdk";
/**
 * The colours a widget may have.
 *
 * A closed set, declared once and enforced on both sides: the form offers only
 * these, and `WidgetColor` in the module's backend schemas rejects anything
 * else. `color` on a stored widget stays a plain string so a row written before
 * the set existed still reads back.
 */
export const WIDGET_COLORS = [
  "blue",
  "green",
  "amber",
  "red",
  "violet",
  "slate",
] as const;

export type WidgetColor = (typeof WIDGET_COLORS)[number];

export type Widget = components["schemas"]["WidgetSchema"];

/** One page of the list: the rows, how many there are, and whether more follow. */
export type WidgetPage =
  components["schemas"]["PaginatedResponse_WidgetSchema_"];

export type WidgetCreate = components["schemas"]["WidgetCreate"];

/** What a caller sends: an unsaid quantity is the server's default. */
export type WidgetCreateInput = WithServerDefaults<WidgetCreate, "quantity">;

export type WidgetUpdate = components["schemas"]["WidgetUpdate"];
