import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import {
  AxiosError,
  AxiosHeaders,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";
import ProductionDetailPage from "./ProductionDetailPage";
import type { ProductionOrder } from "@/modules/maker/types/maker";
import { signInWith } from "@/test/auth";

const updateMutate = vi.fn();
const duplicateMutate = vi.fn();
const completeMutate = vi.fn();
const reverseMutate = vi.fn();

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "sonner";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { withLanguage } from "@/test/mocks/i18n";

const draftOrder: ProductionOrder = {
  id: "ord-1",
  organization_id: "org-1",
  output_template_id: "tpl-1",
  output_template_name: "Jar",
  recipe_id: null,
  number: null,
  planned_qty: "5",
  actual_qty: null,
  overproduced: false,
  scrap_qty: null,
  output_location_id: "loc-1",
  status: "DRAFT",
  total_cost: null,
  production_date: null,
  notes: "",
  created_by: null,
  completed_by: null,
  created_at: "2026-01-01T00:00:00Z",
  completed_at: null,
  cancel_reason: null,
  produced_item_id: null,
  produced_item_name: null,
  unit_cost_snapshot: null,
  reference_price_snapshot: null,
  result_per_unit: null,
  result_per_batch: null,
  lines: [],
};

let currentOrder: ProductionOrder = draftOrder;
const stockMovesRead = vi.hoisted(() => ({ failed: false, refetch: vi.fn() }));

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useProductionOrder: () => ({ data: currentOrder, isLoading: false }),
  useOrderStockMoves: () => ({
    data: stockMovesRead.failed ? undefined : [],
    isError: stockMovesRead.failed,
    refetch: stockMovesRead.refetch,
  }),
  useUpdateProductionOrder: () => ({
    mutate: updateMutate,
    isPending: false,
  }),
  useCompleteProduction: () => ({ mutate: completeMutate, isPending: false }),
  useCancelProduction: () => ({ mutate: vi.fn(), isPending: false }),
  useReverseProduction: () => ({ mutate: reverseMutate, isPending: false }),
  useDuplicateProductionOrder: () => ({
    mutate: duplicateMutate,
    isPending: false,
  }),
}));

let currentRecipe: { lines: unknown[] } | undefined = undefined;

// The page reads the order's recipe to know whether the run would consume
// anything; `useModuleQuery` underneath wants a ModulesProvider this test has
// no use for.
vi.mock("@/modules/maker/hooks/useRecipes", () => ({
  useMakerSettings: () => ({ data: { reference_direction: "SAVINGS" } }),
  useMakerRecipe: () => ({ data: currentRecipe }),
}));

let currentPlanned: { entries: Array<Record<string, unknown>> } | undefined =
  undefined;

vi.mock("@/modules/maker/hooks/useCostBreakdown", () => ({
  useCostBreakdown: () => ({ data: currentPlanned }),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/maker/production/ord-1"]}>
          <Routes>
            <Route
              path="/maker/production/:orderId"
              element={<ProductionDetailPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
}

describe("ProductionDetailPage — the manager's cancel", () => {
  it("shows the account that runs the floor a Cancel it cannot press, and why", () => {
    // Taking a run back is the manager's call, the same split the documents
    // module draws: the person at the goods executes, only the manager
    // cancels. The button used to sit on every member's screen, with the 403
    // waiting behind it — and then it was removed without a word, which left
    // the author of a draft unable to withdraw it and not told why.
    currentOrder = draftOrder;
    signInWith(["maker:read", "maker:write"]);
    renderPage();
    expect(
      screen.getByTestId("maker-detail-complete-button"),
    ).toBeInTheDocument();
    const cancel = screen.getByTestId("maker-detail-cancel-button");
    expect(cancel).toBeDisabled();
    expect(cancel.parentElement).toHaveAttribute(
      "title",
      expect.stringMatching(/ask someone who can manage production/i),
    );
  });

  it("offers Cancel to an account holding maker:manage", () => {
    currentOrder = draftOrder;
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    renderPage();
    expect(screen.getByTestId("maker-detail-cancel-button")).toBeEnabled();
  });
});

describe("ProductionDetailPage — the refusal says which shortage happened", () => {
  const shortageError = (shortAtCreate: boolean) => {
    const response: AxiosResponse = {
      data: {
        detail: {
          error: "insufficient_stock",
          short_at_create: shortAtCreate,
          shortages: [
            {
              child_template_id: "tpl-wax",
              child_template_name: "Soy wax",
              needed: "200",
              available: "6",
              shortage: "194",
              uom_symbol: "kg",
              convertible: true,
              available_uom_symbol: "kg",
            },
          ],
        },
      },
      status: 422,
      statusText: "Unprocessable Entity",
      headers: new AxiosHeaders(),
      config: {} as InternalAxiosRequestConfig,
    };
    return new AxiosError(
      "Request failed with status code 422",
      AxiosError.ERR_BAD_REQUEST,
      undefined,
      undefined,
      response,
    );
  };

  it("says the run was never enough when it was born over stock", async () => {
    // An order for 1000 candles against stock for 30 was never satisfiable —
    // "ran out since the draft was created" sent the reader looking for a
    // theft of wax that never happened.
    currentOrder = draftOrder;
    renderPage();
    fireEvent.click(screen.getByTestId("maker-detail-complete-button"));
    const confirmButtons = screen.getAllByRole("button", {
      name: "Complete run",
    });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);

    const [, options] =
      completeMutate.mock.calls[completeMutate.mock.calls.length - 1];
    options.onError(shortageError(true));

    expect(
      await screen.findByText(/never enough for this run/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/ran out since the draft was created/i),
    ).not.toBeInTheDocument();
  });

  it("keeps the ran-out sentence for a run that was satisfiable at birth", async () => {
    currentOrder = draftOrder;
    renderPage();
    fireEvent.click(screen.getByTestId("maker-detail-complete-button"));
    const confirmButtons = screen.getAllByRole("button", {
      name: "Complete run",
    });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);

    const [, options] =
      completeMutate.mock.calls[completeMutate.mock.calls.length - 1];
    options.onError(shortageError(false));

    expect(
      await screen.findByText(/ran out since the draft was created/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/never enough for this run/i),
    ).not.toBeInTheDocument();
  });
});

describe("ProductionDetailPage — the stock moves did not load", () => {
  afterEach(() => {
    stockMovesRead.failed = false;
  });

  it("says so, with a retry, instead of leaving out the table without a word", () => {
    currentOrder = draftOrder;
    stockMovesRead.failed = true;
    signInWith(["maker:read", "maker:write"]);
    renderPage();

    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(stockMovesRead.refetch).toHaveBeenCalledTimes(1);
  });
});

describe("ProductionDetailPage edit + duplicate", () => {
  it("shows an Edit button for DRAFT orders", () => {
    currentOrder = draftOrder;
    renderPage();
    expect(screen.getByTestId("maker-detail-edit-button")).toBeInTheDocument();
  });

  it("shows a Duplicate button for any order", () => {
    currentOrder = draftOrder;
    renderPage();
    expect(
      screen.getByTestId("maker-detail-duplicate-button"),
    ).toBeInTheDocument();
  });

  it("hides the Edit button for non-DRAFT orders but keeps Duplicate", () => {
    currentOrder = { ...draftOrder, status: "COMPLETED" };
    renderPage();
    expect(
      screen.queryByTestId("maker-detail-edit-button"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("maker-detail-duplicate-button"),
    ).toBeInTheDocument();
  });

  it("toggles the edit form and saves via update mutation", () => {
    currentOrder = draftOrder;
    renderPage();
    fireEvent.click(screen.getByTestId("maker-detail-edit-button"));
    expect(screen.getByTestId("maker-order-edit-form")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("maker-edit-planned-qty"), {
      target: { value: "7" },
    });
    fireEvent.click(screen.getByTestId("maker-edit-save"));

    expect(updateMutate).toHaveBeenCalledWith(
      {
        orderId: "ord-1",
        data: { planned_qty: "7", production_date: null, notes: null },
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("calls duplicate mutation with the order id", () => {
    currentOrder = draftOrder;
    renderPage();
    fireEvent.click(screen.getByTestId("maker-detail-duplicate-button"));
    expect(duplicateMutate).toHaveBeenCalledWith(
      "ord-1",
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("surfaces the backend detail message when completing fails", () => {
    currentOrder = draftOrder;
    renderPage();

    fireEvent.click(screen.getByTestId("maker-detail-complete-button"));
    fireEvent.change(screen.getByTestId("maker-complete-actual-qty-input"), {
      target: { value: "6" },
    });
    const confirmButtons = screen.getAllByRole("button", {
      name: "Complete run",
    });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);

    expect(completeMutate).toHaveBeenCalledWith(
      { orderId: "ord-1", data: { actual_qty: "6" } },
      expect.objectContaining({ onError: expect.any(Function) }),
    );

    const [, options] = completeMutate.mock.calls[0];
    const response: AxiosResponse = {
      data: { detail: "Overproduction is disabled in settings" },
      status: 400,
      statusText: "Bad Request",
      headers: new AxiosHeaders(),
      config: {} as InternalAxiosRequestConfig,
    };
    const err = new AxiosError(
      "Request failed with status code 400",
      AxiosError.ERR_BAD_REQUEST,
      undefined,
      undefined,
      response,
    );
    options.onError(err);

    expect(toast.error).toHaveBeenCalledWith(
      "Overproduction is disabled in settings",
    );
  });
});

describe("ProductionDetailPage header identity", () => {
  it("shows a shortened order id with the full value in the tooltip", () => {
    currentOrder = {
      ...draftOrder,
      id: "0756afd7-f267-4522-a07d-050be0e2a71a",
    };
    renderPage();

    const idChip = screen.getByTitle("0756afd7-f267-4522-a07d-050be0e2a71a");
    expect(idChip).toHaveTextContent("0756afd7");
    expect(idChip).not.toHaveTextContent("050be0e2a71a");
  });

  it("does not repeat the product name below the shell header", () => {
    currentOrder = draftOrder;
    renderPage();

    // The shell renders the title; the page body must not print it again.
    expect(screen.queryByText("Jar")).not.toBeInTheDocument();
  });

  it("says the formula is empty before the irreversible step, not after", () => {
    // The 422 used to arrive four screens in: preview → calculator →
    // "Complete run" → "this cannot be undone" → confirm → refused.
    currentOrder = { ...draftOrder, recipe_id: "rec-1" };
    currentRecipe = { lines: [] };
    renderPage();

    fireEvent.click(screen.getByTestId("maker-detail-complete-button"));

    expect(screen.getByRole("alert")).toHaveTextContent(/no ingredients/i);
    const confirmButtons = screen.getAllByRole("button", {
      name: "Complete run",
    });
    expect(confirmButtons[confirmButtons.length - 1]).toBeDisabled();
    currentRecipe = undefined;
  });

  it("shows a draft what the run will take instead of an empty record", () => {
    // Order lines are written at completion, so a draft has none — and the
    // section said "no ingredient lines captured yet", which is also what a
    // BOM with nothing in it earns.
    currentOrder = { ...draftOrder, recipe_id: "rec-1" };
    currentPlanned = {
      entries: [
        {
          child_template_id: "tpl-oats",
          child_template_name: "Oats",
          consumed_qty: "2.000",
          unit: "kg",
          cost: "4.00",
          percentage_of_total: "100.00",
          cost_source: "avco",
        },
      ],
    };
    renderPage();

    expect(screen.getByText("Planned consumption")).toBeInTheDocument();
    expect(screen.getByText("Oats")).toBeInTheDocument();
    expect(
      screen.queryByText(/no ingredients were recorded/i),
    ).not.toBeInTheDocument();
    currentPlanned = undefined;
  });

  it("says a draft would consume nothing when its BOM is empty", () => {
    currentOrder = { ...draftOrder, recipe_id: "rec-1" };
    currentPlanned = { entries: [] };
    renderPage();

    expect(screen.getByText(/would consume nothing/i)).toBeInTheDocument();
    currentPlanned = undefined;
  });

  it("names the produced item instead of linking a bare id", () => {
    currentOrder = {
      ...draftOrder,
      status: "COMPLETED",
      produced_item_id: "11112222-3333-4444-5555-666677778888",
      produced_item_name: "Jar of jam",
    };
    renderPage();

    expect(
      screen.getByTitle("11112222-3333-4444-5555-666677778888"),
    ).toHaveTextContent("Jar of jam");
  });
});

describe("ProductionDetailPage — one quantity convention per screen", () => {
  it("writes the header summary and the complete-dialog placeholder alike", async () => {
    // The header said "Planowano 10 pcs" while the field beneath it hinted
    // "10 szt." — one screen, two conventions, three lines apart. Both now
    // come from the module's one quantity formatter.
    const setHeader = vi.fn();
    currentOrder = {
      ...draftOrder,
      planned_qty: "10.000",
      output_uom_symbol: "pcs",
    };
    signInWith(["maker:read", "maker:write"]);

    await withLanguage("pl", () => {
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      render(
        <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
          <QueryClientProvider client={qc}>
            <MemoryRouter initialEntries={["/maker/production/ord-1"]}>
              <Routes>
                <Route
                  path="/maker/production/:orderId"
                  element={<ProductionDetailPage />}
                />
              </Routes>
            </MemoryRouter>
          </QueryClientProvider>
        </PageHeaderContext.Provider>,
      );

      const subtitle = setHeader.mock.calls
        .map((call) => call[0]?.subtitle)
        .join(" ");
      expect(subtitle).toContain("Planowano 10 szt.");
      expect(subtitle).not.toMatch(/pcs/);

      fireEvent.click(screen.getByTestId("maker-detail-complete-button"));
      const input = screen.getByTestId("maker-complete-actual-qty-input");
      expect(input).toHaveAttribute("placeholder", "10 szt.");
    });
  });
});

describe("ProductionDetailPage — the forecast is the refusal's own list", () => {
  const orderShort = (items: ProductionOrder["shortage_items"]) => ({
    ...draftOrder,
    recipe_id: "rec-1",
    shortage_count: items?.length ?? 0,
    shortage_items: items,
  });

  const waxEntry = {
    child_template_id: "tpl-wax",
    child_template_name: "Soy wax",
    consumed_qty: "40.000",
    unit: "kg",
    cost: "4.00",
    percentage_of_total: "100.00",
    cost_source: "avco",
  };

  it("marks the rows the refusal names, straight from the server's list", () => {
    // The banner and the rows used to come from two different minds: the
    // count from the server, the markers from a browser forecast that
    // disagreed with it — and on a run the server refuses, the rows under
    // "1 ingredient short" carried no marker at all.
    currentOrder = orderShort([
      {
        child_template_id: "tpl-wax",
        child_template_name: "Soy wax",
        needed: "40",
        available: "6",
        shortage: "34",
        uom_symbol: "kg",
        convertible: true,
      },
    ]);
    currentPlanned = { entries: [waxEntry] };
    renderPage();

    expect(screen.getByText(/1 ingredient short/i)).toBeInTheDocument();
    expect(screen.getByTestId("maker-planned-short")).toHaveTextContent(
      /short 34 kg/,
    );
    currentPlanned = undefined;
  });

  it("says the units cannot be compared when the server could not either", () => {
    currentOrder = orderShort([
      {
        child_template_id: "tpl-wax",
        child_template_name: "Soy wax",
        needed: "1",
        available: "5",
        shortage: null,
        uom_symbol: "kg",
        convertible: false,
        available_uom_symbol: "pcs",
      },
    ]);
    currentPlanned = { entries: [waxEntry] };
    renderPage();

    expect(screen.getByText(/1 ingredient short/i)).toBeInTheDocument();
    expect(screen.getByTestId("maker-planned-short")).toHaveTextContent(
      /units cannot be compared/,
    );
    expect(screen.queryByText(/short \d/)).not.toBeInTheDocument();
    currentPlanned = undefined;
  });
});

describe("ProductionDetailPage — undoing a completed run", () => {
  const completed: ProductionOrder = {
    ...draftOrder,
    status: "COMPLETED",
    actual_qty: "2",
    completed_at: "2026-01-02T00:00:00Z",
  };

  it("takes a completed run back after asking, for a manager", () => {
    // A completed run offered only Duplicate: a typo of 20 for 2 took ten
    // times the ingredients out of stock with no way back from this page.
    currentOrder = completed;
    reverseMutate.mockClear();
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Undo run" }));
    expect(reverseMutate).not.toHaveBeenCalled();
    expect(
      screen.getByText(/go back to the locations and batches/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Yes, undo run" }));

    expect(reverseMutate).toHaveBeenCalledWith("ord-1", expect.any(Object));
  });

  it("tells the floor account why it cannot undo the run", () => {
    currentOrder = completed;
    signInWith(["maker:read", "maker:write"]);
    renderPage();
    const undo = screen.getByTestId("maker-detail-reverse-button");
    expect(undo).toBeDisabled();
    expect(undo.parentElement).toHaveAttribute(
      "title",
      expect.stringMatching(/ask someone who can manage production/i),
    );
  });

  it("offers no undo where nothing was posted, or once it is undone", () => {
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    for (const status of ["DRAFT", "CANCELLED", "REVERSED"] as const) {
      currentOrder = { ...draftOrder, status };
      const { unmount } = renderPage();
      expect(screen.queryByTestId("maker-detail-reverse-button")).toBeNull();
      unmount();
    }
  });
});

describe("ProductionDetailPage — the action row fits a phone", () => {
  it("wraps instead of running off the screen, in every state", () => {
    // The row carried the status badge and up to four buttons in one
    // unwrapped flex line: at 390 px it ran past the edge under an
    // overflow-hidden ancestor, so "Complete run" was cut mid-label and
    // "Duplicate" was off the screen entirely — the only ways to finish or
    // duplicate a draft order. The warehouse module's action row
    // (DocumentActionButtons) wraps; this one does too now, and the pin
    // holds for every status the page can show, since the set of actions
    // changes with the state.
    for (const status of [
      "DRAFT",
      "COMPLETED",
      "CANCELLED",
      "REVERSED",
    ] as const) {
      currentOrder = { ...draftOrder, status };
      const { unmount } = renderPage();
      const row = screen.getByTestId(
        "maker-detail-duplicate-button",
      ).parentElement;
      expect(row?.className).toContain("flex-wrap");
      unmount();
    }
  });
});

describe("ProductionDetailPage — the draft says when its quantities are read", () => {
  it("tells the reader the BOM is read at completion, not frozen at creation", () => {
    // Editing a BOM line while an order is open changes what that order
    // will take off the shelf — a recorded design decision (fresh
    // expansion, the recipe journal as its witness). The draft used to
    // show the forecast as if it were a promise; the section now says the
    // quantities are read from the BOM when the run closes.
    currentOrder = { ...draftOrder, recipe_id: "rec-1" };
    currentPlanned = {
      entries: [
        {
          child_template_id: "tpl-oats",
          child_template_name: "Oats",
          consumed_qty: "2.000",
          unit: "kg",
          cost: "4.00",
          percentage_of_total: "100.00",
          cost_source: "avco",
        },
      ],
    };
    renderPage();

    expect(
      screen.getByText(/read from the BOM when the run closes/i),
    ).toBeInTheDocument();
    currentPlanned = undefined;
  });

  it("says the ingredients go as planned whatever the actual quantity", () => {
    // Under-production consumes the full planned ingredients — recorded
    // decision (consumption against planned, output against actual). The
    // completion dialog is the last place to say so before the
    // irreversible click; the hint used to stop at scrap and overproduction.
    currentOrder = { ...draftOrder, recipe_id: "rec-1" };
    currentPlanned = { entries: [] };
    renderPage();

    fireEvent.click(screen.getByTestId("maker-detail-complete-button"));
    expect(
      screen.getByText(/consumed as planned regardless/i),
    ).toBeInTheDocument();
    currentPlanned = undefined;
  });
});
