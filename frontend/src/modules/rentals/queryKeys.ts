/**
 * React Query keys of the rentals module.
 *
 * Every key starts with `rentals`, and the object is named `queryKeys` so the
 * invalidation gate sees one root for the module's writes.
 */
export const queryKeys = {
  rentals: {
    all: ["rentals"] as const,
    today: () => ["rentals", "today"] as const,
    calendar: (
      startsAt: string,
      endsAt: string,
      model?: string,
      category?: string,
    ) =>
      [
        "rentals",
        "calendar",
        startsAt,
        endsAt,
        model ?? "",
        category ?? "",
      ] as const,
    bookings: (params: Record<string, unknown>) =>
      ["rentals", "bookings", params] as const,
    booking: (id: string) => ["rentals", "booking", id] as const,
    kits: () => ["rentals", "kits"] as const,
    kit: (id: string) => ["rentals", "kit", id] as const,
    blocks: (params: Record<string, unknown>) =>
      ["rentals", "blocks", params] as const,
    bufferRules: () => ["rentals", "buffer-rules"] as const,
    assets: (search: string, category?: string) =>
      ["rentals", "assets", search, category ?? ""] as const,
    models: () => ["rentals", "models"] as const,
    categories: () => ["rentals", "categories"] as const,
    partners: () => ["rentals", "partners"] as const,
    members: () => ["rentals", "members"] as const,
  },
};
