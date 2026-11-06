import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
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

// This screen hides its actions from an account that cannot use them,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  signInWith(["purchase_orders:read", "purchase_orders:write"]);
});

afterEach(() => {
  signOut();
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    warning: vi.fn(),
  },
}));

// The suppliers come from the partners module, which the page asks only while
// that module is on.
const modules = vi.hoisted(() => ({ enabled: ["purchase_orders"] }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: modules.enabled,
    isModuleEnabled: (name: string) => modules.enabled.includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * `openEdit` used to build the form state with the template id in the
 * field named `name`, so the first caller that showed `form.product.name` in
 * edit mode would print a UUID. The API returns `product_name` — the form
 * must carry it. The modal is mocked so the test can read the form state the
 * page hands it.
 */
const formProp = vi.fn();
/** The whole prop object: a spec that has to drive the save button itself. */
const modalProps = vi.fn();
vi.mock("@/modules/purchase_orders/components/ReorderRuleFormModal", () => ({
  ReorderRuleFormModal: (props: { form: unknown }) => {
    formProp(props.form);
    modalProps(props);
    return <div data-testid="rule-form-modal" />;
  },
  emptyForm: {
    id: null,
    product: null,
    locationId: "",
    minQuantity: "",
    maxQuantity: "",
    safetyStock: "0",
    preferredPartnerId: "",
    notes: "",
  },
}));

const RULE = {
  id: "rule-1",
  product_template_id: "tpl-abc",
  product_name: "Latte cups",
  uom_id: "uom-1",
  uom_symbol: "pcs",
  location_id: "loc-1",
  min_quantity: 2,
  max_quantity: 10,
  safety_stock: 1,
  preferred_partner_id: "p-1",
  preferred_partner_name: "ACME",
  notes: null,
};

/** The requests the page made of the locations endpoint. */
let locationRequests: URLSearchParams[] = [];

function mockApi() {
  locationRequests = serveLocations([
    { id: "loc-1", name: "Cold Storage" },
    ...Array.from({ length: 1500 }, (_, i) => ({
      id: `bin-${i}`,
      name: `Bin ${i}`,
    })),
  ]);
  server.use(
    http.get("/api/v1/purchase-orders/reorder-rules", () =>
      HttpResponse.json(onePage([RULE])),
    ),
    http.get("/api/v1/purchase-orders/replenishment/alerts", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/partners", () =>
      HttpResponse.json({
        items: [{ id: "p-1", name: "ACME", type: "SUPPLIER" }],
        total: 1,
      }),
    ),
    http.get("/api/v1/partners/p-1", () =>
      HttpResponse.json({
        id: "p-1",
        name: "ACME",
        type: "SUPPLIER",
        is_active: true,
      }),
    ),
    http.get("/api/v1/items/product-templates/count", () =>
      HttpResponse.json({ count: 5 }),
    ),
  );
}

/** Stands in for the shell: renders whatever the page puts in the header. */
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

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
};

describe("ReorderRulesPage edit form state", () => {
  beforeEach(() => {
    mockApi();
    modules.enabled = ["purchase_orders"];
    formProp.mockClear();
  });

  it("names where a rule points without reading the organization's locations", async () => {
    render(<PageHost />, { wrapper: createWrapper() });

    expect(await screen.findByText("Cold Storage")).toBeInTheDocument();
    // Every read was the named place or one page of the picker, never the lot.
    expect(
      locationRequests.every(
        (r) => r.getAll("ids").length > 0 || Number(r.get("limit")) <= 30,
      ),
    ).toBe(true);
    expect(
      locationRequests.some((r) => r.getAll("ids").includes("loc-1")),
    ).toBe(true);
  });

  it("disables the add-rule CTA and shows the hint on an empty catalog", async () => {
    server.use(
      http.get("/api/v1/items/product-templates/count", () =>
        HttpResponse.json({ count: 0 }),
      ),
    );
    render(<PageHost />, { wrapper: createWrapper() });

    const addButton = await screen.findByRole("button", {
      name: "Add rule",
    });
    await waitFor(() => expect(addButton).toBeDisabled());
    expect(
      await screen.findByText(/If you don't have any products yet/),
    ).toBeInTheDocument();
  });

  it("says the alerts could not be loaded instead of showing none", async () => {
    server.use(
      http.get(
        "/api/v1/purchase-orders/replenishment/alerts",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(<PageHost />, { wrapper: createWrapper() });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("says the suppliers could not be loaded instead of offering none", async () => {
    modules.enabled = ["purchase_orders", "partners"];
    server.use(
      http.get(
        "/api/v1/partners",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(<PageHost />, { wrapper: createWrapper() });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("names the preferred suppliers from the rules, without reading each partner", async () => {
    modules.enabled = ["purchase_orders", "partners"];
    const readById: string[] = [];
    server.use(
      http.get("/api/v1/purchase-orders/reorder-rules", () =>
        HttpResponse.json(
          onePage([
            {
              ...RULE,
              preferred_partner_id: "p-900",
              preferred_partner_name: "Supplier 900",
            },
            {
              ...RULE,
              id: "rule-2",
              preferred_partner_id: "p-901",
              preferred_partner_name: "Supplier 901",
            },
          ]),
        ),
      ),
      http.get("/api/v1/partners/:id", ({ params }) => {
        readById.push(String(params.id));
        return HttpResponse.json({ id: params.id, name: "wrong" });
      }),
    );
    render(<PageHost />, { wrapper: createWrapper() });

    expect(await screen.findByText("Supplier 900")).toBeInTheDocument();
    expect(screen.getByText("Supplier 901")).toBeInTheDocument();
    expect(readById).toEqual([]);
  });

  it("looks the typed supplier up on the server instead of in a capped list", async () => {
    modules.enabled = ["purchase_orders", "partners"];
    const asked: URLSearchParams[] = [];
    server.use(
      http.get("/api/v1/partners", ({ request }) => {
        asked.push(new URL(request.url).searchParams);
        return HttpResponse.json({ items: [], total: 0 });
      }),
    );
    render(<PageHost />, { wrapper: createWrapper() });
    await waitFor(() => expect(modalProps).toHaveBeenCalled());

    act(() => {
      const props = modalProps.mock.calls.at(-1)?.[0] as {
        onPartnerSearch: (query: string) => void;
      };
      props.onPartnerSearch("Zed");
    });

    await waitFor(() =>
      expect(asked.some((q) => q.get("search") === "Zed")).toBe(true),
    );
    expect(asked.every((q) => Number(q.get("limit")) <= 50)).toBe(true);
  });

  it("keeps the add-rule CTA enabled when products exist", async () => {
    render(<PageHost />, { wrapper: createWrapper() });

    const addButton = await screen.findByRole("button", {
      name: "Add rule",
    });
    await waitFor(() => expect(addButton).not.toBeDisabled());
    expect(
      screen.queryByText(/If you don't have any products yet/),
    ).not.toBeInTheDocument();
  });

  it("carries the product name into the edit form, not its id", async () => {
    render(<PageHost />, { wrapper: createWrapper() });

    // The table shows the API-provided name.
    expect(await screen.findByText("Latte cups")).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /edit/i }));

    // The mocked modal captures whatever `openEdit` built as the form state.
    await vi.waitFor(() => expect(formProp).toHaveBeenCalled());
    const calls = formProp.mock.calls;
    const form = calls[calls.length - 1]?.[0] as {
      id: string | null;
      product: {
        name: string;
        product_template_id: string;
        uom_id: string | null;
        uom_symbol: string | null;
      } | null;
    };
    expect(form.id).toBe("rule-1");
    expect(form.product?.name).toBe("Latte cups");
    // The regression this guards against: the UUID used to stand in for the
    // name.
    expect(form.product?.name).not.toBe("tpl-abc");
    expect(form.product?.product_template_id).toBe("tpl-abc");
  });

  it("prefills the thresholds as plain numbers, not as the wire's padded decimals", async () => {
    // "2.000" in a number input reads "2,000" in a comma-decimal browser — two
    // thousand to anyone who reads the digits the English way.
    server.use(
      http.get("/api/v1/purchase-orders/reorder-rules", () =>
        HttpResponse.json(
          onePage([
            {
              ...RULE,
              min_quantity: "2.000",
              max_quantity: "10.500",
              safety_stock: "1.000",
            },
          ]),
        ),
      ),
    );
    render(<PageHost />, { wrapper: createWrapper() });

    expect(await screen.findByText("Latte cups")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /edit/i }));

    await vi.waitFor(() => expect(formProp).toHaveBeenCalled());
    const calls = formProp.mock.calls;
    const form = calls[calls.length - 1]?.[0] as {
      minQuantity: string;
      maxQuantity: string;
      safetyStock: string;
    };
    expect(form.minQuantity).toBe("2");
    expect(form.maxQuantity).toBe("10.5");
    expect(form.safetyStock).toBe("1");
  });

  it("carries the product unit into the edit form, not dropping it", async () => {
    render(<PageHost />, { wrapper: createWrapper() });

    expect(await screen.findByText("Latte cups")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /edit/i }));

    await vi.waitFor(() => expect(formProp).toHaveBeenCalled());
    const calls = formProp.mock.calls;
    const form = calls[calls.length - 1]?.[0] as {
      product: { uom_id: string | null; uom_symbol: string | null } | null;
    };
    expect(form.product?.uom_id).toBe("uom-1");
    expect(form.product?.uom_symbol).toBe("pcs");
  });
});

/**
 * A save that wants more than the shelf holds still succeeds, and the warning
 * beside it has two numbers to place. It used to put the shelf's limit in the
 * sentence's "it wants {{max}}": a rule asking for 300 on a shelf that holds
 * 200 read "it wants 200", which is the shelf's number in the rule's mouth —
 * the opposite of what happened. The warehouse module has said it the other
 * way round since it was written ("wants {{reorder}} … holds ({{max}})").
 */
describe("ReorderRulesPage — a save that outruns the shelf", () => {
  beforeEach(() => {
    mockApi();
    formProp.mockClear();
    modalProps.mockClear();
    vi.mocked(toast.warning).mockClear();
    server.use(
      http.patch("/api/v1/purchase-orders/reorder-rules/rule-1", () =>
        HttpResponse.json({
          ...RULE,
          max_quantity: 300,
          capacity_max_quantity: "200",
          over_capacity: true,
        }),
      ),
    );
  });

  it("gives each number to the side it belongs to", async () => {
    render(<PageHost />, { wrapper: createWrapper() });

    fireEvent.click(await screen.findByRole("button", { name: /edit/i }));
    await vi.waitFor(() => expect(formProp).toHaveBeenCalled());

    // The rule asks for 300; the shelf answers 200. Type it in the form the
    // way the reader would.
    const propsNow = () =>
      modalProps.mock.calls[modalProps.mock.calls.length - 1]?.[0] as {
        form: { maxQuantity: string };
        onChange: (next: unknown) => void;
        onSave: () => Promise<void>;
      };
    await act(async () => {
      propsNow().onChange({ ...propsNow().form, maxQuantity: "300" });
    });
    await vi.waitFor(() =>
      expect(
        formProp.mock.calls[formProp.mock.calls.length - 1]?.[0],
      ).toMatchObject({ maxQuantity: "300" }),
    );

    await act(async () => {
      await propsNow().onSave();
    });

    expect(toast.warning).toHaveBeenCalledWith(
      "Rule saved. Note: it wants 300 per replenishment — more than the shelf holds (200).",
    );
  });
});
