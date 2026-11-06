import { useCallback, useState } from "react";
import { render, screen, fireEvent, waitFor, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import PricelistPage from "./PricelistPage";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const PRODUCT = {
  product_template_id: "tpl-1",
  name: "Latte cups",
  sku: null,
  barcode: null,
  brand: null,
  uom_id: "uom-1",
  uom_symbol: null,
  image_url: null,
  is_stub: false,
};

const ENTRY = {
  id: "pl-1",
  organization_id: "org-1",
  partner_id: "p-1",
  product_template_id: "tpl-1",
  product_name: "Latte cups",
  unit_price: "4.20",
  currency: "PLN",
  uom_id: null,
  min_quantity: "10",
  valid_from: "2026-01-01",
  valid_to: null,
  notes: null,
};

let created: unknown[];
let patched: unknown[];
let deleted: string[];

function mockApi() {
  server.use(
    http.get("/api/v1/partners", () =>
      HttpResponse.json({
        items: [{ id: "p-1", name: "Cold Storage Co", type: "SUPPLIER" }],
        total: 1,
      }),
    ),
    http.get("/api/v1/purchase-orders/pricelist/by-partner/:id", () =>
      HttpResponse.json(onePage([ENTRY])),
    ),
    http.get("/api/v1/items/product-templates/count", () =>
      HttpResponse.json({ count: 5 }),
    ),
    http.get("/api/v1/warehouse/product-search", () =>
      HttpResponse.json([PRODUCT]),
    ),
    http.post("/api/v1/purchase-orders/pricelist", async ({ request }) => {
      created.push(await request.json());
      return HttpResponse.json({ ...ENTRY, id: "pl-2" });
    }),
    http.patch("/api/v1/purchase-orders/pricelist/:id", async ({ request }) => {
      patched.push(await request.json());
      return HttpResponse.json(ENTRY);
    }),
    http.delete("/api/v1/purchase-orders/pricelist/:id", ({ params }) => {
      deleted.push(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }),
  );
}

function PageHost() {
  const [data, setData] = useState<PageHeaderData>({});
  const setHeader = useCallback((next: PageHeaderData) => setData(next), []);
  return (
    <PageHeaderContext.Provider value={{ data, setHeader }}>
      <div>{data.actions}</div>
      <PricelistPage />
    </PageHeaderContext.Provider>
  );
}

async function pickSupplier() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("combobox", { name: "Supplier" }));
  await user.click(
    await screen.findByRole("button", { name: "Cold Storage Co" }),
  );
  await screen.findByRole("button", { name: /edit latte cups/i });
}

async function openCreateForm() {
  fireEvent.click(
    (await screen.findAllByRole("button", { name: "Add price" }))[0],
  );
  return screen.findByRole("dialog");
}

/**
 * The supplier price list writes what the form says: a new price carries the
 * picked supplier and product, an edit patches only the entry it opened, a
 * delete waits for the confirmation, and a refused duplicate keeps the form
 * open with a sentence the reader can act on. A save that dropped the
 * supplier, sent empty strings for blank optional fields, or closed the form
 * on a refusal fails here.
 */
describe("PricelistPage — saving and removing prices", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    created = [];
    patched = [];
    deleted = [];
    withModules("partners", "purchase_orders");
    signInWith(["purchase_orders:read", "purchase_orders:write"]);
    mockApi();
  });

  afterEach(() => {
    signOut();
  });

  it("adds a price for the picked supplier and product, blanks as null", async () => {
    render(<PageHost />);
    await pickSupplier();
    const dialog = await openCreateForm();

    fireEvent.change(within(dialog).getByLabelText(/^Product/), {
      target: { value: "la" },
    });
    fireEvent.click(
      await screen.findByText("Latte cups", { selector: "*:not(td)" }),
    );
    fireEvent.change(within(dialog).getByLabelText(/^Price/), {
      target: { value: "12.5" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      partner_id: "p-1",
      product_template_id: "tpl-1",
      uom_id: "uom-1",
      unit_price: 12.5,
      min_quantity: null,
      valid_to: null,
      notes: null,
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Price added"),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("proposes the day the form is opened on, not the day the app loaded", async () => {
    render(<PageHost />);
    await pickSupplier();
    // The page has been open for a while; the clock moves on to another day
    // before the form is opened.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2031, 2, 4, 0, 10));
    try {
      const dialog = await openCreateForm();
      fireEvent.change(within(dialog).getByLabelText(/^Product/), {
        target: { value: "la" },
      });
      fireEvent.click(
        await screen.findByText("Latte cups", { selector: "*:not(td)" }),
      );
      fireEvent.change(within(dialog).getByLabelText(/^Price/), {
        target: { value: "3" },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

      await waitFor(() => expect(created).toHaveLength(1));
      expect(created[0]).toMatchObject({ valid_from: "2031-03-04" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("refuses to save a new price before a product is picked", async () => {
    render(<PageHost />);
    await pickSupplier();
    const dialog = await openCreateForm();
    fireEvent.change(within(dialog).getByLabelText(/^Price/), {
      target: { value: "3" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    // The refusal sits on the product field, which is marked required.
    expect(
      await within(dialog).findByText("Select a product first"),
    ).toBeVisible();
    expect(
      within(dialog).getByRole("combobox", { name: /Product/ }),
    ).toHaveAttribute("aria-required", "true");
    expect(created).toEqual([]);
  });

  it("keeps the form open with its own sentence when the price is a duplicate", async () => {
    server.use(
      http.patch("/api/v1/purchase-orders/pricelist/:id", () =>
        HttpResponse.json(
          { detail: { code: "PRICELIST_DUPLICATE", message: "dup" } },
          { status: 409 },
        ),
      ),
    );
    render(<PageHost />);
    await pickSupplier();
    fireEvent.click(screen.getByRole("button", { name: /edit latte cups/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("already has a price"),
      ),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("patches the entry it opened, with the edited price", async () => {
    render(<PageHost />);
    await pickSupplier();
    fireEvent.click(screen.getByRole("button", { name: /edit latte cups/i }));
    const dialog = await screen.findByRole("dialog");
    // The product is fixed on an existing entry, so the picker is gone.
    expect(within(dialog).queryByLabelText(/^Product/)).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Price/), {
      target: { value: "5" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patched).toHaveLength(1));
    expect(patched[0]).toMatchObject({
      unit_price: 5,
      currency: "PLN",
      min_quantity: 10,
      valid_from: "2026-01-01",
    });
    expect(created).toEqual([]);
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Price updated"),
    );
  });

  it("deletes an entry only after the confirmation", async () => {
    const user = userEvent.setup();
    render(<PageHost />);
    await pickSupplier();

    await user.click(
      screen.getByRole("button", { name: /delete latte cups/i }),
    );
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(deleted).toEqual([]);

    await user.click(
      screen.getByRole("button", { name: /delete latte cups/i }),
    );
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toEqual(["pl-1"]));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Price removed"),
    );
  });

  it("toasts a refused delete as an error", async () => {
    server.use(
      http.delete("/api/v1/purchase-orders/pricelist/:id", () =>
        HttpResponse.json({ detail: "In use" }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    render(<PageHost />);
    await pickSupplier();
    await user.click(
      screen.getByRole("button", { name: /delete latte cups/i }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("In use"));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("closes the form on Cancel without saving", async () => {
    render(<PageHost />);
    await pickSupplier();
    const dialog = await openCreateForm();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(created).toEqual([]);
  });

  it("retries the supplier's prices after they failed to load", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/purchase-orders/pricelist/by-partner/:id", () => {
        calls += 1;
        return calls === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage([ENTRY]));
      }),
    );
    const user = userEvent.setup();
    render(<PageHost />);
    await user.click(await screen.findByRole("combobox", { name: "Supplier" }));
    await user.click(
      await screen.findByRole("button", { name: "Cold Storage Co" }),
    );
    await user.click(await screen.findByRole("button", { name: /try again/i }));
    expect(
      await screen.findByRole("button", { name: /edit latte cups/i }),
    ).toBeInTheDocument();
  });

  it("retries the supplier list after it failed to load", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/partners", () => {
        calls += 1;
        return calls === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json({ items: [], total: 0 });
      }),
    );
    const user = userEvent.setup();
    render(<PageHost />);
    await user.click(await screen.findByRole("button", { name: /try again/i }));
    await waitFor(() => expect(calls).toBeGreaterThan(1));
  });
});
