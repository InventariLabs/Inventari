import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import type { Item, StorageLocation, StorageLocationSummary } from "@/types";
import { StorageProductsTab } from "./StorageProductsTab";

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useAllCategories: () => ({ data: [] }),
}));
vi.mock("@/modules/spaces/hooks/useStorageMutations", () => ({
  useConsumeItemFromStorage: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteItemFromStorage: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/modules/spaces/components/StorageItemsSection", () => ({
  default: ({ filteredItems }: { filteredItems: Item[] }) => (
    <ul>
      {filteredItems.map((item) => (
        <li key={item.id}>{item.name}</li>
      ))}
    </ul>
  ),
}));
vi.mock("./StorageItemModals", () => ({ default: () => null }));

const zone = { id: "zone", name: "Zone" } as StorageLocation;
const zoneRow = {
  id: "zone",
  name: "Zone",
  full_path: "Zone",
  direct_children_count: 2,
} as StorageLocationSummary;
const item = (id: string, name: string) => ({ id, name }) as Item;

beforeEach(() => server.resetHandlers());

describe("StorageProductsTab — include locations inside", () => {
  it("asks once for the place and everything below it, not once per place below", async () => {
    const asked: string[] = [];
    server.use(
      http.get("/api/v1/locations/:id/items", ({ params, request }) => {
        asked.push(`${params.id as string}?${new URL(request.url).search}`);
        const inside = new URL(request.url).searchParams.get("include_inside");
        return HttpResponse.json(
          onePage(
            inside
              ? [item("1", "On the zone"), item("2", "On a shelf below")]
              : [item("1", "On the zone")],
          ),
        );
      }),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <StorageProductsTab
          storage={zone}
          summary={zoneRow}
          isArchived={false}
          canWriteItems
        />
      </QueryClientProvider>,
    );
    await screen.findByText("On the zone");
    expect(screen.queryByText("On a shelf below")).toBeNull();

    await userEvent.click(screen.getByRole("checkbox"));

    await screen.findByText("On a shelf below");
    await waitFor(() => expect(asked).toHaveLength(2));
    expect(asked.every((url) => url.startsWith("zone?"))).toBe(true);
    expect(asked[1]).toContain("include_inside=true");
  });
});

describe("StorageProductsTab — module data hidden", () => {
  it("asks for the general records only, as the counts beside it do", async () => {
    const asked: string[] = [];
    server.use(
      http.get("/api/v1/locations/:id/items", ({ request }) => {
        asked.push(new URL(request.url).search);
        return HttpResponse.json(onePage([item("1", "On the zone")]));
      }),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <StorageProductsTab
          storage={zone}
          summary={zoneRow}
          isArchived={false}
          canWriteItems
          excludeModuleContexts
        />
      </QueryClientProvider>,
    );
    await screen.findByText("On the zone");
    expect(asked[0]).toContain("exclude_module_contexts=true");
  });
});
