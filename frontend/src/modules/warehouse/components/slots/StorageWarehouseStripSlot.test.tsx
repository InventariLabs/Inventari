import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";
import { act, render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import StorageWarehouseStripSlot from "./StorageWarehouseStripSlot";

const data = {
  storageId: "shelf-a",
  storageName: "Shelf A",
  fullPath: "Main Warehouse / Shelf A",
  sequence: 15,
};

const rice = {
  id: "cap-1",
  organization_id: "org",
  location_id: "shelf-a",
  product_template_id: "p1",
  max_quantity: "40",
  location_name: "Shelf A",
  product_template_name: "Jasmine Rice 1kg",
  product_unit_symbol: "pcs",
  reorder_max_quantity: null,
  reorder_over_capacity: false,
};

function cell(fill: number | null) {
  return {
    location_id: "shelf-a",
    location_name: "Shelf A",
    entries: [],
    capacity_product_name: null,
    capacity_used: null,
    capacity_max: null,
    capped_products: fill === null ? 0 : 1,
    fill,
    status: fill === null ? "no_limit" : "ok",
    unmeasured: false,
    items_count: 2,
  };
}

function serve(options: {
  entries?: unknown[];
  single?: boolean;
  fill?: number | null;
}) {
  server.use(
    http.get("/api/v1/warehouse/putaway/capacity", () =>
      HttpResponse.json(onePage(options.entries ?? [])),
    ),
    http.get("/api/v1/warehouse/putaway/capacity-settings/:locationId", () =>
      HttpResponse.json({
        location_id: "shelf-a",
        single_product: options.single ?? false,
      }),
    ),
    http.get("/api/v1/warehouse/putaway/occupancy/:locationId", () =>
      HttpResponse.json({
        locations: [cell(options.fill ?? null)],
        signals: [],
      }),
    ),
  );
}

beforeEach(() => {
  signInWith(["warehouse:read", "warehouse:write", "locations:write"]);
});

afterEach(() => {
  signOut();
});

describe("the warehouse strip on a location's settings", () => {
  it("reads walk order, mixing, the one limit and the fill in one line", async () => {
    serve({ entries: [rice], fill: 23 });
    render(<StorageWarehouseStripSlot data={data} />);

    const strip = await screen.findByText(/walk order 15/i);
    expect(strip).toHaveTextContent(
      "walk order 15 · different products · limit: Jasmine Rice 1kg — 40 pcs. · 23%",
    );
  });

  it("counts the limits when there are several, and names one product mix", async () => {
    serve({
      entries: [rice, { ...rice, id: "cap-2", product_template_id: "p2" }],
      single: true,
      fill: 60,
    });
    render(<StorageWarehouseStripSlot data={data} />);

    expect(
      await screen.findByText("walk order 15 · one product · 2 limits · 60%"),
    ).toBeInTheDocument();
  });

  it("says so when there is no walk order and no limit", async () => {
    serve({});
    render(<StorageWarehouseStripSlot data={{ ...data, sequence: null }} />);

    expect(
      await screen.findByText(
        "walk order not set · different products · no limit",
      ),
    ).toBeInTheDocument();
  });

  it("opens the location settings panel from its button", async () => {
    serve({ entries: [rice], fill: 23 });
    render(<StorageWarehouseStripSlot data={data} />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Set up location" }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("dialog", { name: "Location settings" }),
      ).toBeInTheDocument(),
    );
  });

  it("renders nothing, and asks nothing, for an account that may not read documents", async () => {
    signInWith(["locations:read"]);
    let asked = 0;
    server.use(
      http.get("/api/v1/warehouse/documents/*", () => {
        asked += 1;
        return HttpResponse.json([]);
      }),
    );
    const { container } = render(<StorageWarehouseStripSlot data={data} />);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(container).toBeEmptyDOMElement();
    expect(asked).toBe(0);
  });
});
