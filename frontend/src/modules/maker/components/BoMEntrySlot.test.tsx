import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { BoMEntrySlot } from "./BoMEntrySlot";
import type { Item } from "@/types";

let summaryData: {
  items: {
    template_id: string;
    line_count: number;
    default_recipe_id: string | null;
  }[];
} = { items: [] };

vi.mock("@/modules/maker/hooks/useBom", () => ({
  useBomSummary: () => ({ data: summaryData }),
}));

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    id: "item-1",
    location_id: "loc-1",
    category_id: null,
    name: "Sourdough loaf",
    brand: null,
    description: null,
    weight: null,
    quantity: 1,
    added_date: "2026-01-01",
    expiry_date: null,
    freeze_date: null,
    shelf_location: null,
    image_url: null,
    metadata: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    template_id: "tpl-1",
    ...overrides,
  } as Item;
}

/** Echoes the router state so assertions can read what the link carried. */
function StateProbe() {
  const location = useLocation();
  return (
    <div data-testid="probe-state">
      {JSON.stringify(location.state ?? null)}
    </div>
  );
}

function renderSlot(
  item: Item | undefined,
  requestLeave?: (go: () => void) => void,
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/inventory/items"]}>
        <Routes>
          <Route
            path="/inventory/items"
            element={<BoMEntrySlot data={{ item, requestLeave }} />}
          />
          <Route path="/maker" element={<StateProbe />} />
          <Route
            path="/maker/recipes/:recipeId"
            element={<div data-testid="probe-recipe" />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BoMEntrySlot", () => {
  it("opens the default BOM card when the product has one", async () => {
    summaryData = {
      items: [
        { template_id: "tpl-1", line_count: 2, default_recipe_id: "recipe-1" },
      ],
    };
    renderSlot(makeItem());
    fireEvent.click(screen.getByTestId("maker-bom-entry-link"));

    expect(await screen.findByTestId("probe-recipe")).toBeInTheDocument();
  });

  it("sends a product without a BOM to the catalog, not the removed editor", async () => {
    summaryData = { items: [] };
    renderSlot(makeItem());
    fireEvent.click(screen.getByTestId("maker-bom-entry-link"));

    // The regression this guards: the fallback used to point at
    // `/maker/bom?parent=`, a route that no longer exists.
    expect(await screen.findByTestId("probe-state")).toBeInTheDocument();
  });

  it("asks the form it sits in before taking the reader out of it", () => {
    summaryData = { items: [] };
    const requestLeave = vi.fn();
    renderSlot(makeItem(), requestLeave);

    fireEvent.click(screen.getByTestId("maker-bom-entry-link"));

    // Nothing navigated: the host is holding the answer.
    expect(requestLeave).toHaveBeenCalledWith(expect.any(Function));
    expect(screen.queryByTestId("probe-state")).toBeNull();
  });

  it("carries the product to the catalog so the create sheet is preselected", async () => {
    summaryData = { items: [] };
    const { getByTestId } = renderSlot(makeItem());
    fireEvent.click(getByTestId("maker-bom-entry-link"));

    const state = JSON.parse(
      (await screen.findByTestId("probe-state")).textContent ?? "null",
    );
    expect(state.createRecipeFor).toMatchObject({
      product_template_id: "tpl-1",
      name: "Sourdough loaf",
    });
  });

  it("renders nothing for an item with no product template", () => {
    summaryData = { items: [] };
    const { container } = renderSlot(makeItem({ template_id: null }));
    expect(container).toBeEmptyDOMElement();
  });
});
