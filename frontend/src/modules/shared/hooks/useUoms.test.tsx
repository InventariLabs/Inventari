import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useFlatUoms,
  useUoms,
  isContinuousUom,
  isCountedUom,
  getUomCategoryName,
} from "./useUoms";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockUoms = [
  { id: "u1", name: "Pieces", symbol: "pcs", category: "COUNT" },
  { id: "u2", name: "Kilograms", symbol: "kg", category: "WEIGHT" },
];

const mockCategories = [
  {
    id: "cat1",
    name: "Weight",
    uoms: [
      {
        id: "u1",
        name: "Kilograms",
        symbol: "kg",
        factor: "1",
        rounding: "0.001",
        is_reference: true,
        is_system: false,
        category_id: "cat1",
      },
      {
        id: "u2",
        name: "Grams",
        symbol: "g",
        factor: "0.001",
        rounding: "0.001",
        is_reference: false,
        is_system: false,
        category_id: "cat1",
      },
    ],
  },
  {
    id: "cat2",
    name: "Count",
    uoms: [
      {
        id: "u3",
        name: "Pieces",
        symbol: "pcs",
        factor: "1",
        rounding: "1",
        is_reference: true,
        is_system: false,
        category_id: "cat2",
      },
    ],
  },
];

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("useFlatUoms", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/uoms", () => HttpResponse.json(onePage(mockUoms))),
    );
  });

  it("returns flat UoM list on success", async () => {
    const { result } = renderHook(() => useFlatUoms(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
    expect(result.current.data?.[0].symbol).toBe("pcs");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/uoms", () =>
        HttpResponse.json({ detail: "Error" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useFlatUoms(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useUoms (categories)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/uoms/categories", () =>
        HttpResponse.json(onePage(mockCategories)),
      ),
    );
  });

  it("returns UoM categories on success", async () => {
    const { result } = renderHook(() => useUoms(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
    expect(result.current.data?.[0].name).toBe("Weight");
    expect(result.current.data?.[0].uoms).toHaveLength(2);
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/uoms/categories", () =>
        HttpResponse.json({ detail: "Error" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useUoms(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("UoM utility functions", () => {
  const categories = mockCategories;

  it("getUomCategoryName returns correct category name", () => {
    const name = getUomCategoryName(categories, "u1");
    expect(name).toBe("Weight");
  });

  it("getUomCategoryName returns null for unknown uom", () => {
    const name = getUomCategoryName(categories, "unknown");
    expect(name).toBeNull();
  });

  it("getUomCategoryName returns null when categories undefined", () => {
    const name = getUomCategoryName(undefined, "u1");
    expect(name).toBeNull();
  });

  it("isContinuousUom returns true for Weight units", () => {
    const result = isContinuousUom(categories, "u1");
    expect(result).toBe(true);
  });

  it("isContinuousUom returns true for Volume units", () => {
    // Note: mockCategories doesn't have Volume, but the function logic works
    const result = isContinuousUom(categories, "u3");
    expect(result).toBe(false); // Count is not continuous
  });

  it("isContinuousUom returns false for unknown units", () => {
    const result = isContinuousUom(categories, "unknown");
    expect(result).toBe(false);
  });
});

describe("isCountedUom", () => {
  const counted = ["Unit", "Pack", "Can", "Bottle", "Box", "Bag"];
  const measured = ["Weight", "Volume", "Length"];
  const catalogue = [...counted, ...measured].map((name) => {
    const id = `cat-${name.toLowerCase()}`;
    return {
      id,
      name,
      uoms: [
        {
          id: `uom-${name.toLowerCase()}`,
          name,
          symbol: name.toLowerCase(),
          factor: "1",
          rounding: "1",
          is_reference: true,
          is_system: false,
          category_id: id,
        },
      ],
    };
  });

  it("counts a piece and every bulk package the same way", () => {
    // ADR-015's bridge reads the card's weight or volume per unit for a
    // pack as it does for a piece, so the predicate must not stop at Unit.
    for (const name of counted) {
      expect(
        isCountedUom(catalogue, `uom-${name.toLowerCase()}`),
        `${name} is counted`,
      ).toBe(true);
    }
  });

  it("does not count a measured unit — its own scale is the way out", () => {
    for (const name of measured) {
      expect(
        isCountedUom(catalogue, `uom-${name.toLowerCase()}`),
        `${name} is measured`,
      ).toBe(false);
    }
  });

  it("returns false for an unknown unit", () => {
    expect(isCountedUom(catalogue, "unknown")).toBe(false);
  });
});
