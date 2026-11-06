import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import { signInWith, signOut } from "@/test/auth";
import type { Item } from "@/types";
import PutawayCapacityOnItemSlot from "./PutawayCapacityOnItemSlot";

const item = {
  id: "item-1",
  template_id: "p1",
  location_id: "shelf-a",
} as Item;

const limit = {
  id: "cap-1",
  organization_id: "org",
  location_id: "shelf-a",
  product_template_id: "p1",
  max_quantity: "40",
  location_name: "Shelf 1",
  product_template_name: "Jasmine Rice 1kg",
  product_unit_symbol: "pcs",
  reorder_max_quantity: null,
  reorder_over_capacity: false,
};

beforeEach(() => {
  signInWith(["warehouse:read"]);
  server.use(
    http.get("/api/v1/warehouse/putaway/capacity", () =>
      HttpResponse.json(onePage([limit])),
    ),
  );
});

afterEach(() => {
  signOut();
});

describe("the capacity sentence on a product's page", () => {
  it("names the shelf by its path, so two shelves of one name stay two", async () => {
    serveLocations([
      { id: "wa", name: "Warehouse A", parent_id: null },
      { id: "shelf-a", name: "Shelf 1", parent_id: "wa" },
    ]);

    render(<PutawayCapacityOnItemSlot data={{ item }} />);

    expect(await screen.findByText(/Warehouse A › Shelf 1/)).toBeVisible();
  });

  it("keeps the shelf's own name when its path cannot be read", async () => {
    serveLocations([]);

    render(<PutawayCapacityOnItemSlot data={{ item }} />);

    expect(await screen.findByText(/Shelf 1/)).toBeVisible();
  });
});
