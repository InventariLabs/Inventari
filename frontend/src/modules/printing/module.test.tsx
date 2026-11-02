import { Suspense } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { server } from "@/test/mocks/server";
import { signInWith } from "@/test/auth";
import type { Item } from "@/types";
import "./module";
import { useProductLabelRequest } from "./hooks/useProductLabelRequest";

/**
 * What the module hands the shell. The shell loads each contribution on
 * demand, so a wrong import path in the manifest shows only when somebody
 * opens the page or the slot — never in a test of the page itself.
 */
describe("the printing module's contributions, loaded the way the shell loads them", () => {
  const withProviders = (ui: React.ReactElement, path = "/") =>
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <MemoryRouter initialEntries={[path]}>
          <Suspense fallback={<p>loading</p>}>{ui}</Suspense>
        </MemoryRouter>
      </QueryClientProvider>,
    );

  it("keeps the address printed QR codes carry, and it opens the label's scan page", async () => {
    // Stickers already on shelves carry this path; moving it orphans them.
    server.use(
      http.get("/api/v1/labels/scan/STM-0042", () =>
        HttpResponse.json({
          status: "unassigned",
          label_code: "STM-0042",
          action: "show_quick_add",
        }),
      ),
    );
    const [route] = moduleRegistry.getRoutes(["printing"]);
    expect(route.path).toBe("/labels/scan/:code");
    const Page = route.component;

    withProviders(
      <Routes>
        <Route path={route.path} element={<Page />} />
      </Routes>,
      "/labels/scan/STM-0042",
    );

    expect(await screen.findByTestId("label-short-code")).toHaveTextContent(
      "STM-0042",
    );
  });

  it("puts the attach and print buttons on a product page that has a code but no label", async () => {
    signInWith(["items:read", "items:write"]);
    const slots = moduleRegistry.getSlotComponents("item_detail_extra", [
      "printing",
    ]);
    const item = {
      id: "i-1",
      name: "Flour",
      label_code: null,
      barcode: "2000000000015",
    } as unknown as Item;

    withProviders(
      <>
        {slots.map((Slot, index) => (
          <Slot key={index} {...{ data: { item } }} />
        ))}
      </>,
    );

    expect(
      await screen.findByRole("button", { name: "Attach a label" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Print label" }),
    ).toBeInTheDocument();
  });

  it("mounts a sheet host in the shell's notices that opens when the list's bulk action asks", async () => {
    const asked: Record<string, unknown>[] = [];
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
      http.post("/api/v1/printing/product-labels/png", async ({ request }) => {
        asked.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          { detail: { code: "VALIDATION_ERROR", message: "no codes" } },
          { status: 400 },
        );
      }),
    );
    const [Host] = moduleRegistry.getSlotComponents("global_notifications", [
      "printing",
    ]);
    withProviders(<Host />);
    expect(
      screen.queryByRole("heading", { name: "Product labels" }),
    ).toBeNull();

    await act(async () => {
      await moduleRegistry
        .getBulkActions(["printing"])
        .find((a) => a.id === "print-product-labels")!
        .handler(["i-1"]);
    });

    expect(
      await screen.findByRole("heading", { name: "Product labels" }),
    ).toBeInTheDocument();
    // The sheet is for the products the bulk action named.
    await waitFor(() =>
      expect(asked).toEqual([expect.objectContaining({ item_ids: ["i-1"] })]),
    );
    act(() => useProductLabelRequest.getState().close());
  });
});
