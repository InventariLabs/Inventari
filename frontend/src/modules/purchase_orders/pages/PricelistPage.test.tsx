import { useCallback, useState } from "react";
import { render, screen, fireEvent, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import PricelistPage from "./PricelistPage";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";

// This screen hides its actions from an account that cannot use them,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  withModules("partners", "purchase_orders");
  signInWith(["purchase_orders:read", "purchase_orders:write"]);
});

afterEach(() => {
  signOut();
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

/**
 * The price form and the comparison card ask the same endpoint two different
 * questions, and the page held one pair of state variables for both: typing a
 * product into the dialog filled the card behind it and opened that card's
 * dropdown under the overlay, which is what the screenshot caught.
 */

const PRODUCTS = [
  {
    product_template_id: "tpl-1",
    name: "Latte cups",
    sku: null,
    barcode: null,
    brand: null,
    uom_id: null,
    uom_symbol: null,
    image_url: null,
    is_stub: false,
  },
];

function mockApi() {
  server.use(
    http.get("/api/v1/partners", () =>
      HttpResponse.json({
        items: [{ id: "p-1", name: "Cold Storage Co", type: "SUPPLIER" }],
        total: 1,
      }),
    ),
    http.get("/api/v1/purchase-orders/pricelist/by-partner/:id", () =>
      HttpResponse.json([]),
    ),
    http.get("/api/v1/items/product-templates/count", () =>
      HttpResponse.json({ count: 5 }),
    ),
    http.get("/api/v1/warehouse/product-search", () =>
      HttpResponse.json(PRODUCTS),
    ),
  );
}

/** Stands in for the shell: renders whatever the page puts in the header. */
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

/** Picks the one supplier the mock returns, which unlocks the page. */
async function pickSupplier() {
  const user = userEvent.setup();
  // The page carries several comboboxes (the supplier field and the product
  // pickers), so the supplier needs its name, not the bare role.
  await user.click(await screen.findByRole("combobox", { name: "Supplier" }));
  await user.click(
    await screen.findByRole("button", { name: "Cold Storage Co" }),
  );
}

describe("PricelistPage", () => {
  it("keeps the form's product search out of the comparison card", async () => {
    mockApi();
    render(<PageHost />);

    await pickSupplier();
    // After the empty state has its own "Add price" CTA next to the
    // header one — click the header button (first in DOM order).
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Add price" }))[0],
    );

    const dialog = await screen.findByRole("dialog");
    const formSearch = within(dialog).getByLabelText("Product");
    const cardSearch = screen.getByLabelText("Search product…");

    fireEvent.change(formSearch, { target: { value: "la" } });

    // The suggestions render in a portal against the input, so they live on
    // body, not inside the dialog — ask the document, not the dialog.
    expect(await screen.findByText("Latte cups")).toBeInTheDocument();
    expect(formSearch).toHaveValue("la");
    expect(cardSearch).toHaveValue("");
  });

  it("looks a typed supplier up on the server instead of in a capped list", async () => {
    mockApi();
    const asked: URLSearchParams[] = [];
    server.use(
      http.get("/api/v1/partners", ({ request }) => {
        const params = new URL(request.url).searchParams;
        asked.push(params);
        return HttpResponse.json({
          items: params.get("search")
            ? [{ id: "p-9", name: "Zed Wholesale", type: "SUPPLIER" }]
            : [{ id: "p-1", name: "Cold Storage Co", type: "SUPPLIER" }],
          total: 1,
        });
      }),
    );
    render(<PageHost />);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("combobox", { name: "Supplier" }));
    await user.type(
      await screen.findByPlaceholderText("Search suppliers…"),
      "Zed",
    );

    expect(
      await screen.findByRole("button", { name: "Zed Wholesale" }),
    ).toBeInTheDocument();
    expect(asked.every((q) => Number(q.get("limit")) <= 50)).toBe(true);
  });

  it("says the comparison could not be loaded instead of showing no prices", async () => {
    mockApi();
    server.use(
      http.get(
        "/api/v1/purchase-orders/pricelist/by-template/:id",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(<PageHost />);

    fireEvent.change(await screen.findByLabelText("Search product…"), {
      target: { value: "la" },
    });
    fireEvent.click(await screen.findByText("Latte cups"));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("waits for a supplier before offering to price anything", async () => {
    mockApi();
    render(<PageHost />);

    // The table used to answer "No prices yet" on a page with no supplier
    // picked — an answer to a question nobody had asked.
    expect(await screen.findByText("Pick a supplier")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add price" })).toBeDisabled();
  });
});
