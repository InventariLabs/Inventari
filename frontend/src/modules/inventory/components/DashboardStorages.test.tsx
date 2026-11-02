import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { withLanguage } from "@/test/mocks/i18n";
import type { StorageLocationNode } from "@/types";
import type { StorageComposition } from "@/modules/inventory/hooks/useDashboardAttention";
import DashboardStorages from "./DashboardStorages";

function zone(id: string, name: string, count: number): StorageLocationNode {
  return {
    id,
    name,
    parent_id: null,
    usage: "internal",
    location_type_id: null,
    short_code: null,
    context_tag: null,
    items_count: count,
    subtree_items_count: count,
    children_count: 0,
    children: [],
  };
}

const zones = [
  zone("freezer", "Basement freezer", 52),
  zone("shelf", "Laundry shelf", 6),
  zone("kitchen", "Kitchen", 0),
];

function comp(
  zoneId: string,
  count: number,
  s: Partial<StorageComposition["segments"]> = {},
): StorageComposition {
  const segments = { bad: 0, warn: 0, low: 0, ok: 0, ...s };
  segments.ok = count - segments.bad - segments.warn - segments.low;
  return { zoneId, count, segments };
}

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    <MemoryRouter>{children}</MemoryRouter>
  </QueryClientProvider>
);

function renderCard(
  composition: StorageComposition[],
  storageZones: StorageLocationNode[] = zones,
) {
  return render(
    <DashboardStorages storageZones={storageZones} composition={composition} />,
    { wrapper },
  );
}

function rowOf(name: string) {
  return screen.getByText(name).closest("li") as HTMLElement;
}

describe("DashboardStorages", () => {
  const composition = [
    comp("freezer", 52, { warn: 1, low: 2 }),
    comp("shelf", 6),
    comp("kitchen", 0),
  ];

  it("draws each bar as long as its share of the largest zone", () => {
    renderCard(composition);
    const fill = (name: string) =>
      rowOf(name).querySelector("[data-fill]") as HTMLElement | null;
    expect(parseFloat(fill("Basement freezer")!.style.width)).toBe(100);
    expect(parseFloat(fill("Laundry shelf")!.style.width)).toBeCloseTo(
      (6 / 52) * 100,
      3,
    );
  });

  it("colours a zone only where it has something to report", () => {
    renderCard(composition);
    const segments = (name: string) =>
      [...rowOf(name).querySelectorAll("[data-segment]")].map((s) =>
        s.getAttribute("data-segment"),
      );
    expect(segments("Basement freezer")).toEqual(["warn", "low", "ok"]);
    expect(segments("Laundry shelf")).toEqual(["ok"]);
  });

  it("draws no bar for an empty zone, but still shows its zero", () => {
    renderCard(composition);
    const row = rowOf("Kitchen");
    expect(within(row).queryByRole("img")).toBeNull();
    expect(within(row).getByText("0")).toBeInTheDocument();
  });

  it("says in words what the bar shows in colour", () => {
    renderCard(composition);
    const bar = within(rowOf("Basement freezer")).getByRole("img");
    expect(bar).toHaveAccessibleName(/52 records/);
    expect(bar).toHaveAccessibleName(/1 expiring/);
    expect(bar).toHaveAccessibleName(/2 low stock/);
    expect(bar.getAttribute("aria-label")).not.toMatch(/expired/);
  });

  it("names the expired record in the place's line, not only the expiring", () => {
    renderCard([comp("freezer", 5, { bad: 1, warn: 2 }), comp("shelf", 6)]);
    const row = rowOf("Basement freezer");
    expect(within(row).getByText("1 expired · 2 expiring")).toBeInTheDocument();
  });

  it("names in its legend only the colours on the card", () => {
    renderCard(composition);
    const legend = screen.getByRole("list", { name: /legend/i });
    expect(within(legend).getByText(/in order/i)).toBeInTheDocument();
    expect(within(legend).getByText(/expiring/i)).toBeInTheDocument();
    expect(within(legend).getByText(/low stock/i)).toBeInTheDocument();
    expect(within(legend).queryByText(/^expired$/i)).toBeNull();
  });

  it("links the card to the storages list", () => {
    renderCard(composition);
    expect(
      screen
        .getAllByRole("link")
        .some((l) => l.getAttribute("href") === "/inventory/locations"),
    ).toBe(true);
  });

  it("shows at most six zones and leaves the rest to the storages list", () => {
    const many = Array.from({ length: 10 }, (_, i) =>
      zone(`z-${i}`, `Zone ${i}`, i),
    );
    renderCard(
      many.map((z) => comp(z.id, z.subtree_items_count)),
      many,
    );
    expect(screen.getByText("Zone 0")).toBeInTheDocument();
    expect(screen.getByText("Zone 5")).toBeInTheDocument();
    expect(screen.queryByText("Zone 6")).toBeNull();
  });

  it("counts the products of a zone with no sublocations", () => {
    // The old tile branched on children: with none it said "No locations"
    // and stopped, so a cold room holding six products reported nothing.
    renderCard([comp("shelf", 6)]);
    const row = rowOf("Laundry shelf");
    expect(within(row).getByText("6")).toBeInTheDocument();
    expect(within(row).getByRole("img")).toHaveAccessibleName("6 records");
    expect(row).not.toHaveTextContent(/no locations/i);
  });

  it("inflects every count in a language with more than two plural forms", async () => {
    const hall: StorageLocationNode = {
      ...zone("hall", "Hala", 5),
      items_count: 0,
      children_count: 2,
      children: [zone("a", "A", 2), zone("b", "B", 3)],
    };
    await withLanguage("pl", () => {
      renderCard([comp("hall", 5, { warn: 2 })], [hall]);
      const row = rowOf("Hala");
      expect(row).toHaveTextContent("2 miejsca · 2 wygasają");
      expect(within(row).getByRole("img")).toHaveAccessibleName(
        "5 rekordów: 2 wygasają",
      );
    });
  });

  it("keeps every link inside the module shell", () => {
    renderCard(composition);
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).toMatch(/^\/inventory\//);
    }
  });
});

describe("DashboardStorages — the storages did not arrive", () => {
  it("says so with a retry instead of inviting the reader to add the first storage", () => {
    const onRetry = vi.fn();
    render(
      <DashboardStorages
        storageZones={[]}
        composition={[]}
        loadFailed
        onRetry={onRetry}
      />,
      { wrapper },
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
