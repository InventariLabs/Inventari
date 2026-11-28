import type { TFunction } from "i18next";

import { formatDateInZone } from "@/module-sdk";

/**
 * Who holds a unit, and for how long it is really held. `until` is `null` for
 * a hold with no end of its own: a loan past its due date lasts until the
 * return is recorded.
 */
export function holdText(
  t: TFunction<"rentals">,
  timezone: string | undefined,
  name: string,
  from: string | null | undefined,
  until: string | null | undefined,
): string {
  const start = from ? formatDateInZone(from, timezone) : "";
  if (until === null) return t("form.heldOpen", { name, from: start });
  return t("form.busy", {
    name,
    from: start,
    to: until ? formatDateInZone(until, timezone) : "",
  });
}
