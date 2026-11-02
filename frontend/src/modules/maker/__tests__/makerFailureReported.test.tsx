import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { OrderEditForm } from "@/modules/maker/components/OrderEditForm";
import { PricingCalculator } from "@/modules/maker/components/PricingCalculator";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

/**
 * A refused save in production, and the two mutations next to it that only
 * looked like the same fault.
 *
 * The order edit form ran a bare `useMutation` and passed no `onError`, so a
 * refused save left the form exactly as typed with nothing to read — the
 * reader's next move is to close it believing the change went in.
 *
 * The price calculator was reported alongside it, on the same evidence: a
 * `mutate()` with no handler at the call site. It is not the same thing. The
 * failure is rendered in the sheet, under the button that caused it, and it
 * stays there instead of expiring like a toast. The second test pins that,
 * and pins the neighbouring worry too — that a price computed for the
 * previous quantity might sit above the error. It cannot: React Query clears
 * `data` when the next `mutate` starts.
 */
function renderWithQuery(node: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{node}</QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  server.resetHandlers();
});

describe("production reports its failures", () => {
  it("says a refused order edit did not save, and keeps the form open", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
    server.use(
      http.patch("/api/v1/maker/production/orders/o-1", () =>
        HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 }),
      ),
    );

    renderWithQuery(
      <OrderEditForm
        orderId="o-1"
        initial={{ planned_qty: "10", production_date: null, notes: null }}
        onDone={onDone}
      />,
    );

    await user.click(screen.getByTestId("maker-edit-save"));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    // A 500 speaks in the log's words; the reader gets the module's own.
    expect(vi.mocked(toast.error).mock.calls[0]?.[0]).not.toBe(
      "Internal Server Error",
    );
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByTestId("maker-order-edit-form")).toBeInTheDocument();
  });

  it("keeps a failed price calculation on screen and drops the previous price", async () => {
    const user = userEvent.setup();
    let call = 0;
    server.use(
      http.get("/api/v1/maker/pricing/margin/t-1", () =>
        HttpResponse.json({
          template_id: "t-1",
          target_margin_pct: "30",
          is_default: true,
        }),
      ),
      http.post("/api/v1/maker/pricing/compute", () => {
        call += 1;
        if (call === 1) {
          return HttpResponse.json({
            template_id: "t-1",
            produced_qty: "10",
            total_cost: "100.00",
            unit_cost: "10.00",
            target_margin_pct: "30",
            unit_sale_price: "14.29",
            ingredient_count: 2,
            unrated_ingredient_count: 0,
          });
        }
        return new HttpResponse(null, { status: 500 });
      }),
    );

    renderWithQuery(
      <PricingCalculator
        open
        onClose={vi.fn()}
        templateId="t-1"
        producedQty="10"
      />,
    );

    await user.click(screen.getByTestId("maker-pricing-preview-button"));
    expect(await screen.findByText(/14[.,]29/)).toBeInTheDocument();

    await user.click(screen.getByTestId("maker-pricing-preview-button"));

    expect(
      await screen.findByText("Could not calculate the price"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/14[.,]29/)).not.toBeInTheDocument();
  });
});
