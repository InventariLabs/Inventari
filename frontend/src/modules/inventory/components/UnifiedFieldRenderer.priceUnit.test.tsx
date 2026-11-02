import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { afterEach, describe, it, expect, vi } from "vitest";
import i18n from "@/i18n/config";
import UnifiedFieldRenderer from "./UnifiedFieldRenderer";
import type { FieldDefinition } from "@/types";

/**
 * The price field sits directly under "quantity" and a unit button. Somebody
 * holding an invoice for ten kilos of wax at 45 types 45, and every candle made
 * from 0.2 kg is then costed at 9.00 instead of 0.90 — the error multiplies by
 * the pack size, so an oil bought in 500 ml bottles came out 200× high.
 *
 * Everything downstream already treats the number as a rate: a valuation layer
 * opens at that unit cost, AVCO comes off those layers, a production cost is
 * rate × quantity. Only the form was silent. It now names the unit the price is
 * per, using the one actually picked.
 */

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    <BrowserRouter>{children}</BrowserRouter>
  </QueryClientProvider>
);

const priceField: FieldDefinition = {
  key: "purchase_price",
  type: "number",
  label: "fields.purchase_price",
  visible: true,
  required: false,
  is_system: false,
  is_custom: false,
};

function renderPrice(formData: Record<string, unknown>) {
  return render(
    <UnifiedFieldRenderer
      fieldDefinitions={[priceField]}
      formData={formData}
      onChange={vi.fn()}
    />,
    { wrapper },
  );
}

describe("purchase price says which unit it is per", () => {
  it("names the unit once one is picked", async () => {
    // "2" is the Kilogram in the mocked catalogue.
    renderPrice({ purchase_price: "45", uom_id: "2" });

    await waitFor(() =>
      expect(screen.getByText(/per 1 kg/i)).toBeInTheDocument(),
    );
  });

  it("says what the number is not", async () => {
    renderPrice({ purchase_price: "45", uom_id: "2" });

    await waitFor(() =>
      expect(
        screen.getByText(/not the amount paid for the whole quantity/i),
      ).toBeInTheDocument(),
    );
  });

  it("stays quiet when no unit has been chosen", async () => {
    renderPrice({ purchase_price: "45" });

    await waitFor(() =>
      expect(screen.getByLabelText(/purchase price/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/per 1/i)).not.toBeInTheDocument();
  });
});

describe("the unit in the hint is named the way the unit picker names it", () => {
  const originalLanguage = i18n.language;
  afterEach(async () => {
    await act(() => i18n.changeLanguage(originalLanguage));
  });

  // "3" is the Piece in the mocked catalogue, whose symbol is the raw "pcs".
  it.each([
    ["pl", /Za 1 szt\./],
    ["de", /Pro 1 Stk\./],
    ["es", /Por 1 uds\./],
    ["fr", /Pour 1 pcs\./],
    ["en", /Per 1 pcs\./],
  ])("in %s", async (language, hint) => {
    await i18n.changeLanguage(language);
    renderPrice({ purchase_price: "45", uom_id: "3" });

    await waitFor(() => expect(screen.getByText(hint)).toBeInTheDocument());
  });
});
