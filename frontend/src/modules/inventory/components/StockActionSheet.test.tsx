import React from "react";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { QueryClientProvider, QueryClient } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import StockActionSheet from "./StockActionSheet";
import type { LabelScanView } from "@/types";
import { formatDateTime } from "@/utils/formatters";
import i18n from "i18next";

vi.mock("@/components/Slot", () => ({ Slot: () => null }));

const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

const mockData: LabelScanView = {
  status: "product_stock",
  label_code: "STM-0001",
  message_key: "scan:result.product",
  message_params: { product: "Shelf stock" },
  action: "show_stock_actions",
  stock_summary: {
    total_quantity: 3,
    unit: "pcs",
    items: [
      { id: "item-1", expiry_date: null, location: "Pantry", quantity: 2 },
      {
        id: "item-2",
        expiry_date: "2026-12-31",
        location: "Fridge",
        quantity: 1,
      },
    ],
  },
};

// The sheet reads the unit catalogue to restate a partly used package.
const createWrapper =
  () =>
  ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={new QueryClient()}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );

describe("StockActionSheet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders stock items list", () => {
    render(
      <StockActionSheet
        data={mockData}
        onClose={vi.fn()}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Pantry")).toBeInTheDocument();
    expect(screen.getByText("Fridge")).toBeInTheDocument();
  });

  it("identifies an opened record beside a sealed record on the same shelf", () => {
    const data: LabelScanView = {
      ...mockData,
      stock_summary: {
        total_quantity: 2,
        unit: "packs",
        items: [
          { id: "sealed", expiry_date: null, location: "Pantry", quantity: 1 },
          {
            id: "open",
            expiry_date: null,
            location: "Pantry",
            quantity: 1,
            opened_at: "2026-10-15T10:00:00Z",
          },
        ],
      },
    };
    render(
      <StockActionSheet
        data={data}
        onClose={vi.fn()}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(
      screen.getByText(`Opened ${formatDateTime("2026-10-15T10:00:00Z")}`),
    ).toBeInTheDocument();
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    const { container } = render(
      <StockActionSheet
        data={mockData}
        onClose={onClose}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    // Close button is an icon-only button (X icon) — first button in header
    const allButtons = container.querySelectorAll("button");
    fireEvent.click(allButtons[0]);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onConsume with item id when consume is triggered", () => {
    const onConsume = vi.fn();
    const { container } = render(
      <StockActionSheet
        data={mockData}
        onClose={vi.fn()}
        onConsume={onConsume}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    // The action is named "Remove" everywhere since; this sheet was the
    // last screen still saying "Consume".
    const consumeBtn = container.querySelector('button[aria-label="Remove 1"]');
    expect(consumeBtn).not.toBeNull();
    fireEvent.click(consumeBtn!);
    expect(onConsume).toHaveBeenCalled();
  });

  it("gives one action the main weight and keeps success out of the row", () => {
    // "Remove 1 (first to expire)" (primary, rgb(4,120,87)) and "Add to shopping list"
    // (success, rgb(6,95,70)) stood one above the other: two actions of
    // entirely different consequence in two nearly identical greens, which
    // reads as a rendering artefact rather than as a distinction.
    render(
      <StockActionSheet
        data={mockData}
        onClose={vi.fn()}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
        onAddToShoppingList={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );

    const shopping = screen.getByRole("button", {
      name: /Add to shopping list/i,
    });
    expect(shopping.className).not.toContain("bg-success");
    // One filled primary in the stack: the stock action.
    const filled = screen
      .getAllByRole("button")
      .filter((button) => button.className.includes("bg-primary-700"));
    expect(filled).toHaveLength(1);
  });

  it("writes the unit of the total the way the reader's language does", async () => {
    await act(() => i18n.changeLanguage("pl"));
    try {
      render(
        <StockActionSheet
          data={mockData}
          onClose={vi.fn()}
          onConsume={vi.fn()}
          onAddOne={vi.fn()}
          onAdd={vi.fn()}
        />,
        { wrapper: createWrapper() },
      );
      expect(screen.getByText("szt.")).toBeInTheDocument();
      expect(screen.queryByText("pcs")).not.toBeInTheDocument();
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });

  it("returns null when stock_summary is missing", () => {
    const noSummaryData: LabelScanView = {
      ...mockData,
      stock_summary: undefined,
    };
    const { container } = render(
      <StockActionSheet
        data={noSummaryData}
        onClose={vi.fn()}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(container.firstChild).toBeNull();
  });

  describe("record rows", () => {
    const one: LabelScanView = {
      ...mockData,
      stock_summary: {
        total_quantity: 10,
        unit: "pcs",
        items: [
          {
            id: "item-9",
            expiry_date: "2026-12-31",
            location: "Shelf 2",
            location_path: "Warehouse → Rack 4 → Shelf 2",
            location_code: "R4-S2",
            lot: "LOT-77",
            quantity: 10,
            reserved_quantity: 4,
            available_quantity: 6,
          },
        ],
      },
    };

    const renderOne = () =>
      render(
        <StockActionSheet
          data={one}
          onClose={vi.fn()}
          onConsume={vi.fn()}
          onAddOne={vi.fn()}
          onAdd={vi.fn()}
        />,
        { wrapper: createWrapper() },
      );

    it("says where the record stands, its batch and what is reserved", () => {
      renderOne();
      expect(
        screen.getByText("Warehouse → Rack 4 → Shelf 2"),
      ).toBeInTheDocument();
      expect(screen.getByText("R4-S2")).toBeInTheDocument();
      expect(screen.getByText("Batch LOT-77")).toBeInTheDocument();
      expect(screen.getByText("4 reserved, 6 available")).toBeInTheDocument();
    });

    it("opens the record when its row is tapped", () => {
      renderOne();
      fireEvent.click(screen.getByText("Warehouse → Rack 4 → Shelf 2"));
      expect(navigate).toHaveBeenCalledWith("/inventory/items/item-9");
    });

    it("opens the detail page, not an edit form, for a single record", () => {
      renderOne();
      fireEvent.click(screen.getByText("View all details"));
      expect(navigate).toHaveBeenCalledWith("/inventory/items/item-9");
    });

    it("keeps the plus and minus buttons 44 px wide", () => {
      const { container } = renderOne();
      for (const label of ["Remove 1", "Add 1"]) {
        const button = container.querySelector(`button[aria-label="${label}"]`);
        expect(button).toHaveClass("h-11", "w-11");
        expect(button).not.toHaveClass("h-8");
      }
    });
  });
});
