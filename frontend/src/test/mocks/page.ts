import type { Page } from "@/lib/api/client";

/** A whole list as the one page a list endpoint answers with. */
export function onePage<T>(items: T[]): Page<T> {
  return { items, total: items.length, limit: 200, offset: 0, has_more: false };
}
