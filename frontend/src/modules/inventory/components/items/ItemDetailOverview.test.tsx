import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { beforeEach, describe, it, expect, vi } from "vitest";
import { QueryWrapper } from "@/test/queryWrapper";
import ItemDetailOverview from "./ItemDetailOverview";
import type { CategoryDTO, Item, StorageLocationSummary } from "@/types";
import {
  makeLocationField,
  makeStorageSummary,
} from "@/test/factories/storage";

// The one switch every stock-value surface reads.
const showInventoryValue = vi.hoisted(() => ({ current: true }));
vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => showInventoryValue.current,
}));

// Whether the account may change products; a writer unless a test says not.
const mayWrite = vi.hoisted(() => ({ current: true }));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => mayWrite.current,
}));

vi.mock("@/hooks/useMoney", () => ({
  useMoney: () => (value: unknown) => `$${value}`,
}));

beforeEach(() => {
  showInventoryValue.current = true;
  mayWrite.current = true;
});

const shelf = makeStorageSummary({
  id: "loc-1",
  name: "Cold Storage",
  usage: "internal",
});

const consumed = makeStorageSummary({
  id: "loc-virtual",
  name: "Consumed (Virtual)",
  usage: "customer",
});

const categories: CategoryDTO[] = [];

function item(fields: Record<string, unknown>): Item {
  return {
    id: "item-1",
    name: "Butter",
    quantity: 0,
    location_id: "loc-virtual",
    ...fields,
  } as unknown as Item;
}

function renderOverview(props: {
  item: Item;
  storages: StorageLocationSummary[];
}) {
  render(
    <QueryWrapper>
      <ItemDetailOverview
        item={props.item}
        storages={props.storages}
        categories={categories}
      />
    </QueryWrapper>,
  );
}

describe("ItemDetailOverview — where the record is", () => {
  it("names the virtual location the system moved a used-up record to", () => {
    // The record is alive and answers under its address, but the row used
    // to vanish the moment its location left the internal list — the only
    // screen that knew where it was went silent.
    renderOverview({ item: item({}), storages: [shelf, consumed] });

    expect(screen.getByText("Consumed (Virtual)")).toBeInTheDocument();
    expect(screen.getByText("Customer")).toBeInTheDocument();
    // And the way back is named on the record itself, not left to a URL.
    expect(screen.getByText(/brings it back to a shelf/i)).toBeInTheDocument();
  });

  it("writes the weight the way the rest of the app writes amounts", () => {
    // The card printed the serialized column verbatim — "1.6000000000000
    // kg" on every one of the 66 items that had a weight. The conversion
    // now rounds to the gram, and the trailing scale of a numeric column is
    // not precision anybody typed either.
    renderOverview({
      item: item({ weight: "1.600", weight_unit: "kg" }),
      storages: [shelf],
    });

    expect(screen.getByText("1.6 kg")).toBeInTheDocument();
  });

  it("shows a partly used pack as the fraction left, not a whole pack", () => {
    renderOverview({
      item: item({
        location_id: "loc-1",
        quantity: "0.900",
        uom: { symbol: "pack", rounding: "1.000000" },
      }),
      storages: [shelf],
    });

    expect(screen.getByText(/^0\.9\b/)).toBeInTheDocument();
    expect(screen.queryByText(/^1 pack/i)).toBeNull();
  });

  it("says nothing extra for a record on a real shelf", () => {
    renderOverview({
      item: item({ location_id: "loc-1", quantity: 3 }),
      storages: [shelf, consumed],
    });

    expect(screen.getByText("Cold Storage")).toBeInTheDocument();
    expect(screen.queryByText("Customer")).not.toBeInTheDocument();
    expect(screen.queryByText(/brings it back to a shelf/i)).toBeNull();
  });
});

/**
 * The purchase price is stock value read off a form a home profile does not
 * fill. The add form already hides it on `food_home`; the record's own
 * screen kept showing it.
 */
describe("ItemDetailOverview — the value follows the profile's switch", () => {
  it("shows the purchase price where the profile shows stock value", () => {
    renderOverview({
      item: item({ purchase_price: "12.50" }),
      storages: [shelf],
    });

    expect(screen.getByText("$12.50")).toBeInTheDocument();
  });

  it("hides the purchase price where the profile does not show stock value", () => {
    showInventoryValue.current = false;
    renderOverview({
      item: item({ purchase_price: "12.50" }),
      storages: [shelf],
    });

    expect(screen.queryByText("$12.50")).toBeNull();
    expect(screen.queryByText(/purchase price/i)).toBeNull();
  });
});

describe("ItemDetailOverview — the order the product's stock leaves in", () => {
  it("names the product's strategy", () => {
    renderOverview({
      item: item({ template: { id: "t1", removal_strategy: "FEFO" } }),
      storages: [shelf],
    });

    expect(screen.getByText("Issue order")).toBeInTheDocument();
    expect(screen.getByText("FEFO")).toBeInTheDocument();
  });

  it("reads a product with none set as FIFO, as the stock engine does", () => {
    renderOverview({
      item: item({ template: { id: "t1", removal_strategy: null } }),
      storages: [shelf],
    });

    expect(screen.getByText("FIFO")).toBeInTheDocument();
  });

  it("has no row for a record without a product", () => {
    renderOverview({ item: item({}), storages: [shelf] });

    expect(screen.queryByText("Issue order")).not.toBeInTheDocument();
  });
});

describe("ItemDetailOverview — the fields its location asks for", () => {
  // A field set on a warehouse applies to every shelf inside it; the form
  // asks for it and saves the answer in the record's metadata. The overview
  // drew only its fixed rows, so the answer was nowhere to be read back.
  const rackShelf = makeStorageSummary({
    id: "loc-shelf",
    name: "Shelf 3",
    field_definitions: [
      makeLocationField("colour", {
        label: "Colour",
        type: "select",
        options: ["Blue", "Red"],
      }),
    ],
    inherited_field_definitions: [
      {
        ...makeLocationField("opened_on", { label: "Opened on", type: "date" }),
        from_id: "loc-rack",
        from_name: "Rack A",
      },
      {
        ...makeLocationField("fragile", { label: "Fragile", type: "boolean" }),
        from_id: "loc-wh",
        from_name: "Warehouse",
      },
      {
        ...makeLocationField("supplier", { label: "Supplier", type: "text" }),
        from_id: "loc-wh",
        from_name: "Warehouse",
      },
    ],
  });

  it("shows each answered field under its own label, from any level", () => {
    renderOverview({
      item: item({
        location_id: "loc-shelf",
        quantity: 1,
        metadata: {
          colour: "Blue",
          opened_on: "2026-10-20",
          fragile: true,
          off_enriched: true,
        },
      }),
      storages: [rackShelf],
    });

    expect(screen.getByText("Colour")).toBeInTheDocument();
    expect(screen.getByText("Blue")).toBeInTheDocument();
    expect(screen.getByText("Opened on")).toBeInTheDocument();
    expect(screen.queryByText("2026-10-20")).not.toBeInTheDocument();
    expect(screen.getByText("Fragile")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
    // A field nobody answered stays absent, like every other empty row.
    expect(screen.queryByText("Supplier")).not.toBeInTheDocument();
  });

  it("reads a saved no as an answer, not as a blank", () => {
    // The form stores false only when someone unticks the box, and an
    // imported "no" lands as false: both are answers the reader must see.
    renderOverview({
      item: item({
        location_id: "loc-shelf",
        quantity: 1,
        metadata: { fragile: false },
      }),
      storages: [rackShelf],
    });

    expect(screen.getByText("Fragile")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
  });
});

describe("ItemDetailOverview — a label put on the wrong product", () => {
  it("frees the label from the product page, after asking", async () => {
    const freed: string[] = [];
    server.use(
      http.post("/api/v1/labels/pool/:code/unassign", ({ params }) => {
        freed.push(String(params.code));
        return HttpResponse.json({ message: "Label is now free for reuse" });
      }),
    );
    const user = userEvent.setup();
    renderOverview({
      item: item({ label_code: "STM-0042", location_id: "loc-1" }),
      storages: [shelf],
    });

    await user.click(
      screen.getByRole("button", { name: "Free label STM-0042" }),
    );
    // Nothing happens until the question is answered.
    expect(freed).toEqual([]);
    await user.click(await screen.findByRole("button", { name: "Free label" }));

    await waitFor(() => expect(freed).toEqual(["STM-0042"]));
  });

  it("offers nothing to an account that may not change products", () => {
    mayWrite.current = false;
    renderOverview({
      item: item({ label_code: "STM-0042", location_id: "loc-1" }),
      storages: [shelf],
    });

    expect(screen.getByText("STM-0042")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Free label/ })).toBeNull();
  });

  it("offers nothing on a product with no label", () => {
    renderOverview({ item: item({ location_id: "loc-1" }), storages: [shelf] });

    expect(screen.queryByRole("button", { name: /^Free label/ })).toBeNull();
  });
});
