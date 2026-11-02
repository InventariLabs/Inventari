import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import ReorderRulesPage from "./ReorderRulesPage";
import { signInWith, signOut } from "@/test/auth";
import { onePage } from "@/test/mocks/page";
import { serveLocations } from "@/test/serveLocations";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["purchase_orders"],
    isModuleEnabled: (name: string) => name === "purchase_orders",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const RULE = {
  id: "rule-1",
  product_template_id: "tpl-abc",
  product_name: "Latte cups",
  uom_id: null,
  uom_symbol: null,
  location_id: "loc-1",
  min_quantity: "2",
  max_quantity: "10",
  safety_stock: "1",
  preferred_partner_id: null,
  notes: null,
};

const PRODUCT = {
  product_template_id: "tpl-new",
  name: "Oat milk",
  sku: null,
  barcode: null,
  brand: null,
  uom_id: null,
  uom_symbol: null,
  image_url: null,
  is_stub: false,
};

let created: unknown[];
let deleted: string[];

function mockApi() {
  serveLocations([{ id: "loc-1", name: "Cold Storage" }]);
  server.use(
    http.get("/api/v1/purchase-orders/reorder-rules", () =>
      HttpResponse.json(onePage([RULE])),
    ),
    http.get("/api/v1/purchase-orders/replenishment/alerts", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/items/product-templates/count", () =>
      HttpResponse.json({ count: 5 }),
    ),
    http.get("/api/v1/warehouse/product-search", () =>
      HttpResponse.json([PRODUCT]),
    ),
    http.post("/api/v1/purchase-orders/reorder-rules", async ({ request }) => {
      created.push(await request.json());
      return HttpResponse.json({ ...RULE, id: "rule-2", over_capacity: false });
    }),
    http.delete("/api/v1/purchase-orders/reorder-rules/:id", ({ params }) => {
      deleted.push(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }),
  );
}

function PageHost() {
  const [data, setData] = React.useState<PageHeaderData>({});
  const setHeader = React.useCallback(
    (next: PageHeaderData) => setData(next),
    [],
  );
  return (
    <PageHeaderContext.Provider value={{ data, setHeader }}>
      <div>{data.actions}</div>
      <ReorderRulesPage />
    </PageHeaderContext.Provider>
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PageHost />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Creating a rule goes through the real form: the product picked in it and
 * the location chosen are what is posted, and a rule without either is
 * refused with a sentence. Removing a rule waits for the confirmation and
 * toasts a refusal. A save that posted without a product, or a delete that
 * fired on the first press, fails here.
 */
describe("ReorderRulesPage — creating and removing rules", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    created = [];
    deleted = [];
    signInWith(["purchase_orders:read", "purchase_orders:write"]);
    mockApi();
  });

  afterEach(() => signOut());

  it("creates a rule for the picked product and location", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    const dialog = await screen.findByRole("dialog");

    fireEvent.change(within(dialog).getByLabelText("Product"), {
      target: { value: "oat" },
    });
    fireEvent.click(await screen.findByText("Oat milk"));
    fireEvent.click(within(dialog).getByRole("combobox", { name: "Location" }));
    fireEvent.click(
      await within(document.body)
        .findAllByText("Cold Storage")
        .then((n) => n[n.length - 1]),
    );
    fireEvent.change(within(dialog).getByRole("spinbutton", { name: "Min" }), {
      target: { value: "3" },
    });
    fireEvent.change(within(dialog).getByRole("spinbutton", { name: "Max" }), {
      target: { value: "12" },
    });
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      product_template_id: "tpl-new",
      location_id: "loc-1",
      min_quantity: 3,
      max_quantity: 12,
      preferred_partner_id: null,
      notes: null,
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Rule created"),
    );
  });

  it("refuses a rule with no product, and then one with no location", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("spinbutton", { name: "Min" }), {
      target: { value: "3" },
    });
    fireEvent.change(within(dialog).getByRole("spinbutton", { name: "Max" }), {
      target: { value: "12" },
    });
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(toast.error).toHaveBeenCalledWith("Select a product first");

    fireEvent.change(within(dialog).getByLabelText("Product"), {
      target: { value: "oat" },
    });
    fireEvent.click(await screen.findByText("Oat milk"));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(toast.error).toHaveBeenCalledWith("Select a location");
    expect(created).toEqual([]);

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("removes a rule only after the confirmation; a refusal is toasted", async () => {
    const user = userEvent.setup();
    renderPage();
    const remove = await screen.findByRole("button", {
      name: /delete latte cups/i,
    });
    await user.click(remove);
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(deleted).toEqual([]);

    await user.click(
      screen.getByRole("button", { name: /delete latte cups/i }),
    );
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toEqual(["rule-1"]));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Rule removed"),
    );

    server.use(
      http.delete("/api/v1/purchase-orders/reorder-rules/:id", () =>
        HttpResponse.json({ detail: "In use" }, { status: 409 }),
      ),
    );
    await user.click(
      screen.getByRole("button", { name: /delete latte cups/i }),
    );
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("In use"));
  });

  it("retries the rules and the alerts after they failed", async () => {
    let rules = 0;
    let alerts = 0;
    server.use(
      http.get("/api/v1/purchase-orders/reorder-rules", () => {
        rules += 1;
        return rules === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage([RULE]));
      }),
      http.get("/api/v1/purchase-orders/replenishment/alerts", () => {
        alerts += 1;
        return alerts === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage([]));
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /try again/i }).length).toBe(
        2,
      ),
    );
    for (const retry of screen.getAllByRole("button", { name: /try again/i })) {
      await user.click(retry);
    }
    expect(
      await screen.findByRole("button", { name: /edit latte cups/i }),
    ).toBeInTheDocument();
    expect(alerts).toBeGreaterThan(1);
  });
});
