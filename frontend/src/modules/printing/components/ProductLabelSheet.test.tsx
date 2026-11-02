import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@/i18n/config";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { server } from "@/test/mocks/server";
import type { Item } from "@/types";
import "@/modules/printing/module";
import { useProductLabelRequest } from "@/modules/printing/hooks/useProductLabelRequest";
import { BarcodeLabelSheet } from "@/modules/shared/components/BarcodeLabelSheet";
import ProductLabelPrintSlot from "./ProductLabelPrintSlot";
import ProductLabelSheetHost from "./ProductLabelSheetHost";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => ["printing"],
}));

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);

// jsdom's Blob cannot read itself, so a refusal that arrives as a blob would
// never reach the screen here; the browser has had the method since 2019
// (the same gap client.blob.test.ts fills).
if (typeof Blob.prototype.text !== "function") {
  Blob.prototype.text = function (this: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}

let queryClient: QueryClient;

function renderWithClient(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("ProductLabelSheet", () => {
  let asked: Record<string, unknown>[];

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    asked = [];
    window.URL.createObjectURL = vi.fn(() => "blob:labels");
    window.URL.revokeObjectURL = vi.fn();
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(
          onePage([
            {
              id: "a-1",
              name: "desk",
              printer_type: "brother-p710bt",
              last_seen_at: "2026-10-17T10:00:00Z",
              online: true,
            },
          ]),
        ),
      ),
      http.post("/api/v1/printing/product-labels/png", async ({ request }) => {
        asked.push((await request.json()) as Record<string, unknown>);
        return new HttpResponse(PNG, {
          headers: {
            "Content-Type": "image/png",
            "X-Labels-Without-Code": "1",
          },
        });
      }),
    );
  });

  afterEach(async () => {
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
  });

  it("previews the chosen products and says which have no code", async () => {
    renderWithClient(
      <BarcodeLabelSheet
        target={{ itemIds: ["i-1", "i-2"] }}
        onClose={vi.fn()}
      />,
    );

    expect(
      await screen.findByAltText("Preview of the product labels"),
    ).toHaveAttribute("src", "blob:labels");
    expect(asked[0]).toMatchObject({
      item_ids: ["i-1", "i-2"],
      copies: 1,
      details: true,
    });
    expect(
      screen.getByText(/1 of the chosen products has no code/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download 1 label" }),
    ).toBeEnabled();
  });

  it("leaves the lot and expiry option off when no product has either", async () => {
    server.use(
      http.post(
        "/api/v1/printing/product-labels/png",
        () =>
          new HttpResponse(PNG, {
            headers: {
              "Content-Type": "image/png",
              "X-Labels-Without-Code": "0",
              "X-Labels-With-Details": "0",
            },
          }),
      ),
    );
    renderWithClient(
      <BarcodeLabelSheet target={{ itemIds: ["i-1"] }} onClose={vi.fn()} />,
    );
    await screen.findByAltText("Preview of the product labels");

    expect(
      screen.getByRole("checkbox", { name: "Lot and expiry date" }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        /have no lot or expiry date, so there is nothing to add/,
      ),
    ).toBeInTheDocument();
  });

  it("keeps the lot and expiry option when some product has a date", async () => {
    server.use(
      http.post(
        "/api/v1/printing/product-labels/png",
        () =>
          new HttpResponse(PNG, {
            headers: {
              "Content-Type": "image/png",
              "X-Labels-Without-Code": "0",
              "X-Labels-With-Details": "1",
            },
          }),
      ),
    );
    renderWithClient(
      <BarcodeLabelSheet
        target={{ itemIds: ["i-1", "i-2"] }}
        onClose={vi.fn()}
      />,
    );
    await screen.findByAltText("Preview of the product labels");

    expect(
      screen.getByRole("checkbox", { name: "Lot and expiry date" }),
    ).toBeEnabled();
    expect(screen.queryByText(/nothing to add/)).not.toBeInTheDocument();
  });

  it("shows the refusal when none of the products has a code", async () => {
    server.use(
      http.post("/api/v1/printing/product-labels/png", () =>
        HttpResponse.json(
          {
            detail: {
              code: "VALIDATION_ERROR",
              message:
                "Nothing to print: none of the chosen products has a code.",
            },
          },
          { status: 400 },
        ),
      ),
    );

    renderWithClient(
      <BarcodeLabelSheet target={{ itemIds: ["i-1"] }} onClose={vi.fn()} />,
    );

    expect(
      await screen.findByText(
        "Nothing to print: none of the chosen products has a code.",
      ),
    ).toBeInTheDocument();
  });

  it("sends the products to the printer as product labels", async () => {
    let queued: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/printing/jobs", async ({ request }) => {
        queued = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "job-1" }, { status: 201 });
      }),
    );
    const onClose = vi.fn();
    renderWithClient(
      <BarcodeLabelSheet target={{ itemIds: ["i-1"] }} onClose={onClose} />,
    );
    await screen.findByAltText("Preview of the product labels");

    await userEvent.click(
      await screen.findByRole("button", { name: "Send to printer" }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(queued).toMatchObject({ item_ids: ["i-1"], details: true });
  });
});

describe("product label doors", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    server.use(
      http.get("/api/v1/printing/agents", () => HttpResponse.json(onePage([]))),
      http.post("/api/v1/printing/product-labels/png", () =>
        HttpResponse.json(
          { detail: { code: "VALIDATION_ERROR", message: "x" } },
          { status: 400 },
        ),
      ),
    );
  });

  afterEach(async () => {
    act(() => useProductLabelRequest.getState().close());
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
  });

  it("offers the product page's button only for a product with a code", () => {
    const { rerender } = renderWithClient(
      <ProductLabelPrintSlot
        data={{ item: { id: "i-1", barcode: null } as unknown as Item }}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Print label" }),
    ).not.toBeInTheDocument();

    rerender(
      <QueryClientProvider client={queryClient}>
        <ProductLabelPrintSlot
          data={{
            item: { id: "i-1", barcode: "2000000000015" } as unknown as Item,
          }}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: "Print label" })).toBeVisible();
  });

  // The form saves a generated code on the product, and a SKU only ever
  // lives there: the button answers to both, as the label service does.
  it.each([
    ["product barcode", { barcode: "2000000000015", sku: null }],
    ["product SKU", { barcode: null, sku: "WH-00099" }],
  ])("offers the button for a code that is the %s", (_, template) => {
    renderWithClient(
      <ProductLabelPrintSlot
        data={{
          item: { id: "i-1", barcode: null, template } as unknown as Item,
        }}
      />,
    );
    expect(screen.getByRole("button", { name: "Print label" })).toBeVisible();
  });

  it("opens the sheet from the list's bulk action", async () => {
    renderWithClient(<ProductLabelSheetHost />);
    const action = moduleRegistry
      .getBulkActions(["printing"])
      .find((a) => a.id === "print-product-labels");
    expect(action).toBeDefined();

    await act(async () => {
      await action!.handler(["i-1", "i-2"]);
    });

    expect(
      await screen.findByRole("heading", { name: "Product labels" }),
    ).toBeInTheDocument();
    // The preview's answer lands before the test ends, not after it.
    expect(await screen.findByText("x")).toBeInTheDocument();
  });

  it("opens the sheet for this product from the page button and closes it again", async () => {
    const user = userEvent.setup();
    renderWithClient(
      <ProductLabelPrintSlot
        data={{
          item: { id: "i-1", barcode: "2000000000015" } as unknown as Item,
        }}
      />,
    );
    expect(
      screen.queryByRole("heading", { name: "Product labels" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Print label" }));
    expect(
      await screen.findByRole("heading", { name: "Product labels" }),
    ).toBeInTheDocument();
    // The preview's answer lands before the test ends, not after it.
    expect(await screen.findByText("x")).toBeInTheDocument();

    // The sheet has a cross in its header and a Close at its foot.
    await user.click(screen.getAllByRole("button", { name: "Close" })[0]);
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Product labels" }),
      ).not.toBeInTheDocument(),
    );
  });
});
