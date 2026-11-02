import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { onePage } from "@/test/mocks/page";
import { render, screen, within } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { makeStorageSummary } from "@/test/factories/storage";
import type { StorageLocation } from "@/types";
import { StorageProductsTab } from "./StorageProductsTab";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// The tab with its real list and its real mutations: what the reader sees
// after a write is the point, so neither is stubbed here.
const summary = makeStorageSummary({
  id: "warehouse",
  name: "Warehouse",
  full_path: "Warehouse",
  direct_children_count: 1,
});
const storage = summary as unknown as StorageLocation;

interface Row {
  id: string;
  name: string;
  quantity: string;
  storage_location_id: string;
}

/** Serves the warehouse's own row and one row on a shelf inside it, from
 *  one mutable shelf so a write changes what the next read answers. */
function serveShelf(insideAnswered: Promise<void> = Promise.resolve()) {
  const rows: Row[] = [
    {
      id: "p1",
      name: "Pallet wrap",
      quantity: "5",
      storage_location_id: "warehouse",
    },
    {
      id: "p2",
      name: "Boxed screws",
      quantity: "41",
      storage_location_id: "shelf",
    },
  ];
  const asJson = (row: Row) => ({
    ...row,
    category_id: null,
    is_deleted: false,
  });
  server.use(
    http.get("/api/v1/locations/:id/items", async ({ request }) => {
      const inside = new URL(request.url).searchParams.get("include_inside");
      if (!inside) {
        return HttpResponse.json(
          onePage(
            rows
              .filter((row) => row.storage_location_id === "warehouse")
              .map(asJson),
          ),
        );
      }
      await insideAnswered;
      return HttpResponse.json(onePage(rows.map(asJson)));
    }),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    http.patch("/api/v1/items/:id/consume", ({ params }) => {
      const row = rows.find((candidate) => candidate.id === params.id)!;
      row.quantity = String(Number(row.quantity) - 1);
      return HttpResponse.json({
        ...asJson(row),
        uom: { symbol: "pcs", rounding: "1" },
      });
    }),
    http.delete("/api/v1/items/:id", ({ params }) => {
      rows.splice(
        rows.findIndex((candidate) => candidate.id === params.id),
        1,
      );
      return new HttpResponse(null, { status: 204 });
    }),
  );
}

function renderTab() {
  render(
    <StorageProductsTab
      storage={storage}
      summary={summary}
      isArchived={false}
      canWriteItems
    />,
  );
}

async function includeInside() {
  await screen.findAllByText("Pallet wrap");
  await userEvent.click(screen.getByLabelText("Include locations inside"));
}

const tableRow = async (name: string) =>
  within(await screen.findByRole("table")).findByRole("row", {
    name: new RegExp(name),
  });

describe("a location's products with the locations inside", () => {
  it("says it is still reading instead of showing its own rows as the whole list", async () => {
    let answer = () => undefined as void;
    serveShelf(new Promise<void>((done) => (answer = done)));
    renderTab();

    await includeInside();

    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(screen.queryAllByText("Pallet wrap")).toHaveLength(0);

    answer();
    expect(await screen.findAllByText("Boxed screws")).not.toHaveLength(0);
    expect(screen.getAllByText("Pallet wrap")).not.toHaveLength(0);
  });

  it("shows the new quantity of a product consumed on a shelf inside", async () => {
    serveShelf();
    renderTab();
    await includeInside();
    const row = await tableRow("Boxed screws");
    expect(within(row).getByText("41")).toBeInTheDocument();

    await userEvent.click(within(row).getByRole("button", { name: "Remove" }));

    expect(
      await within(await tableRow("Boxed screws")).findByText("40"),
    ).toBeInTheDocument();
  });

  it("takes away a product deleted from a shelf inside", async () => {
    serveShelf();
    renderTab();
    await includeInside();

    await userEvent.click(
      within(await tableRow("Boxed screws")).getByRole("button", {
        name: "Delete",
      }),
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Delete",
      }),
    );

    await vi.waitFor(() =>
      expect(screen.queryAllByText("Boxed screws")).toHaveLength(0),
    );
    expect(screen.getAllByText("Pallet wrap")).not.toHaveLength(0);
  });

  it("says one unit was taken and how much is left, not the remainder as taken", async () => {
    serveShelf();
    renderTab();
    await includeInside();

    await userEvent.click(
      within(await tableRow("Boxed screws")).getByRole("button", {
        name: "Remove",
      }),
    );

    await vi.waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Removed 1 unit — 40 pcs. left",
      ),
    );
  });
});
