import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { PurchaseNotesSection } from "./PurchaseNotesSection";
import type { EquipmentFormData } from "../pages/AddEquipmentPage";

const form = {
  purchase_price: "",
  purchase_date: "",
  warranty_until: "",
  notes: "",
} as EquipmentFormData;

function renderSection() {
  server.use(
    http.get("*/organizations/my", () =>
      HttpResponse.json({
        id: "org-1",
        name: "Test Org",
        currency: "PLN",
        created_at: "2026-01-01T00:00:00Z",
        created_by: null,
        enabled_modules: ["core", "items", "equipment"],
        settings: {},
      }),
    ),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PurchaseNotesSection form={form} onSet={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("PurchaseNotesSection", () => {
  /**
   * The label used to be hand-rolled and inline, which left the price field
   * about 8px below the date field beside it in the same grid row. Asking for
   * the control by its label is what proves the component renders it.
   */
  it("reaches the price field through its label", async () => {
    renderSection();

    const price = await screen.findByLabelText(/purchase price/i);
    expect(price).toHaveAttribute("type", "number");
  });

  it("describes the amount with the organization's currency", async () => {
    renderSection();

    // The currency arrives with the organization, so wait for it rather than
    // for the field — the field renders before the query settles.
    await screen.findByText("PLN");
    expect(
      screen.getByLabelText(/purchase price/i),
    ).toHaveAccessibleDescription("PLN");
  });
});

/**
 * The section owns no state: every edit is handed to the page under the
 * form key it belongs to. The failure caught: a field wired to the wrong
 * key, so the price lands in the notes (or nowhere) on save.
 */
describe("PurchaseNotesSection — edits reach the page's form", () => {
  it("hands the price and the notes back under their own keys", () => {
    const onSet = vi.fn();
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ id: "org-1", name: "Test Org", currency: "PLN" }),
      ),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PurchaseNotesSection form={form} onSet={onSet} />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText(/purchase price/i), {
      target: { value: "1299.00" },
    });
    fireEvent.change(screen.getByLabelText("Notes"), {
      target: { value: "Bought with the docking station" },
    });

    expect(onSet).toHaveBeenCalledWith("purchase_price", "1299.00");
    expect(onSet).toHaveBeenCalledWith(
      "notes",
      "Bought with the docking station",
    );
  });
});
