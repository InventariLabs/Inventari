import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The row under test needs nothing but the item; the tab's other cards
// each reach for the network, so they are stubbed to keep the measurement
// about the one value.
vi.mock("@/modules/equipment/components/ValuationCard", () => ({
  ValuationCard: () => null,
}));
const assetImage = vi.hoisted(() => ({
  current: null as { url: string | null; fromModel: boolean } | null,
}));
vi.mock("@/modules/equipment/hooks/useAssetImage", () => ({
  useAssetImage: () => () => assetImage.current,
}));
vi.mock("@/modules/equipment/hooks/useLocationLabel", () => ({
  useLocationLabel:
    () => (id: string | null | undefined, name: string | null) =>
      (id === "loc-home" ? "Server Rack B" : null) ?? name,
}));
vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCategories: () => ({ data: [] }),
  useAllCategories: () => ({ data: [] }),
}));
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "USD",
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/utils/helpers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/helpers")>()),
  downloadBlob: vi.fn(),
}));

import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import userEvent from "@testing-library/user-event";
import { server } from "@/test/mocks/server";
import { downloadBlob } from "@/utils/helpers";
import { render, screen, waitFor } from "@/test/utils";
import { InfoTab } from "./AssetInfoTab";
import type { Item } from "@/types";

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    id: "asset-1",
    name: "ThinkPad T14s",
    quantity: 1,
    ...overrides,
  } as unknown as Item;
}

describe("InfoTab — image card", () => {
  beforeEach(() => {
    assetImage.current = { url: "/uploads/laptop.png", fromModel: false };
  });

  afterEach(() => {
    assetImage.current = null;
  });

  it("offers to delete a live asset's own picture", () => {
    render(<InfoTab item={makeItem({ image_url: "/uploads/laptop.png" })} />);

    expect(
      screen.getByRole("button", { name: /delete image/i }),
    ).toBeInTheDocument();
  });

  it("does not offer to delete an archived asset's picture", () => {
    // DELETE /items/{id}/image resolves through the live-only item read and
    // answers ITEM_ARCHIVED, so the archived card must not offer the action
    // the API will refuse.
    render(
      <InfoTab
        item={makeItem({ image_url: "/uploads/laptop.png", is_deleted: true })}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /delete image/i }),
    ).not.toBeInTheDocument();
  });
});

describe("InfoTab — Purchase & Warranty", () => {
  it("prints the purchase price the API actually sends", () => {
    // `Decimal` crosses the wire as a JSON string ("4599.00"), which is
    // what the generated contract says and what the row never accepted:
    // a `typeof === "number"` guard made this row read "—" for every
    // asset in the database, while the valuation card twelve rows below
    // printed the same value correctly.
    render(<InfoTab item={makeItem({ purchase_price: "4599.00" })} />);

    expect(screen.getByText(/4,599\.00/)).toBeInTheDocument();
  });

  it("still says nothing when there is no purchase price", () => {
    render(<InfoTab item={makeItem({ purchase_price: null })} />);

    expect(screen.queryByText(/4,599\.00/)).not.toBeInTheDocument();
    // The label stays on screen; it is the value that is empty.
    expect(screen.getByText(/Purchase Price/i)).toBeInTheDocument();
  });
});

describe("InfoTab — who has it", () => {
  // The module's question is "who has it right now", and the page that a
  // scanned QR code opens answered it only on the Assignments tab: the
  // first screen said "Checked out" and nothing about by whom.
  const assignment = (over: Record<string, unknown> = {}) =>
    ({
      id: "a-1",
      item_id: "asset-1",
      holder_name: "Ava Brennan",
      holder_kind: "person",
      assigned_to_name: "Ava Brennan",
      assigned_to_email: "ava.brennan@example.com",
      checkout_location_id: null,
      checked_out_at: "2026-10-22T09:00:00Z",
      expected_return_at: "2026-10-30T21:59:59Z",
      checked_in_at: null,
      ...over,
    }) as never;

  it("names the holder and the expected return on the first tab", () => {
    render(<InfoTab item={makeItem()} activeAssignment={assignment()} />);

    expect(screen.getByText("Held by")).toBeInTheDocument();
    expect(screen.getByText("Ava Brennan")).toBeInTheDocument();
    expect(screen.getByText("ava.brennan@example.com")).toBeInTheDocument();
    const due = screen.getByText("Expected return").nextElementSibling;
    expect(due?.textContent).toMatch(/30|2026/);
    expect(due?.textContent).not.toBe("—");
  });

  it("names a place as the place it stands in", () => {
    render(
      <InfoTab
        item={makeItem()}
        activeAssignment={assignment({
          holder_name: "Workstations",
          holder_kind: "location",
          assigned_to_name: "",
          assigned_to_email: null,
          checkout_location_id: "loc-1",
          checkout_location_name: "Workstations",
        })}
      />,
    );

    expect(screen.getByText("Stands in")).toBeInTheDocument();
    expect(screen.queryByText("Held by")).not.toBeInTheDocument();
  });

  // Checked out to a place, the asset stands there — the Location row says
  // so, with the home the return will bring it back to beneath it. It used to
  // name the home alone while the list's holder column named the place.
  it("gives a placed asset one location: the place, with its home beneath", () => {
    render(
      <InfoTab
        item={makeItem({ location_id: "loc-home" })}
        activeAssignment={assignment({
          holder_name: "Workstations",
          holder_kind: "location",
          assigned_to_name: "",
          assigned_to_email: null,
          checkout_location_id: "loc-ws",
          checkout_location_name: "Workstations",
        })}
      />,
    );

    expect(screen.getByRole("link", { name: "Workstations" })).toHaveAttribute(
      "href",
      "/equipment/assets?location=loc-ws",
    );
    expect(screen.getByText("Returns to Server Rack B")).toBeInTheDocument();
  });

  it("says nothing about a holder when nobody has it", () => {
    render(<InfoTab item={makeItem()} activeAssignment={null} />);

    expect(screen.queryByText("Held by")).not.toBeInTheDocument();
  });
});

/**
 * The tab's two writes: deleting the asset's own picture and downloading
 * its QR label. The failures caught: a delete that leaves the detail page
 * showing the old picture (the caller is never told), a download saved
 * under the wrong name, and either failing with nothing said.
 */
describe("InfoTab — the picture and the label", () => {
  afterEach(() => {
    assetImage.current = null;
  });

  it("deletes the picture, tells the page, and says so", async () => {
    assetImage.current = { url: "/uploads/laptop.png", fromModel: false };
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/items/asset-1/image", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const onImageChanged = vi.fn();
    render(
      <InfoTab
        item={makeItem({ image_url: "/uploads/laptop.png" })}
        onImageChanged={onImageChanged}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: /delete image/i }),
    );
    await waitFor(() => expect(onImageChanged).toHaveBeenCalled());
    expect(deleted).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith("Image deleted");
  });

  it("keeps the picture and says so when the delete fails", async () => {
    assetImage.current = { url: "/uploads/laptop.png", fromModel: false };
    server.use(
      http.delete("/api/v1/items/asset-1/image", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );
    const onImageChanged = vi.fn();
    render(
      <InfoTab
        item={makeItem({ image_url: "/uploads/laptop.png" })}
        onImageChanged={onImageChanged}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: /delete image/i }),
    );
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onImageChanged).not.toHaveBeenCalled();
  });

  it("downloads the QR label under the asset's code", async () => {
    let codes: string[] = [];
    server.use(
      http.get("/api/v1/labels/pool/export/png", ({ request }) => {
        codes = new URL(request.url).searchParams.getAll("short_codes");
        return new HttpResponse(new Blob(["png"]));
      }),
    );
    render(<InfoTab item={makeItem({ label_code: "EQP-0042" })} />);

    await userEvent.click(screen.getByRole("button", { name: /Download/ }));
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(
        expect.anything(),
        "EQP-0042.png",
      ),
    );
    expect(codes).toEqual(["EQP-0042"]);
  });

  it("says the label could not be downloaded", async () => {
    server.use(
      http.get("/api/v1/labels/pool/export/png", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );
    render(<InfoTab item={makeItem({ label_code: "EQP-0042" })} />);

    await userEvent.click(screen.getByRole("button", { name: /Download/ }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(downloadBlob).not.toHaveBeenCalled();
  });
});
