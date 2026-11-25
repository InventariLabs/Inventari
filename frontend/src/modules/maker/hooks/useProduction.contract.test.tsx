import type { ReactNode } from "react";
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { recordRequests } from "@/test/requestLog";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useAddPortion,
  useAddShortagesToShoppingList,
  useCancelProduction,
  useCompleteProduction,
  useCreateProductionOrder,
  useDuplicateProductionOrder,
  useFinishProduction,
  useMakerMonthlyResult,
  useOrderStockMoves,
  useProductionOrder,
  useProductionOrders,
  useProductionPreview,
  useRecordMadeProduction,
  useReverseProduction,
  useStartProduction,
  useTickStep,
  useUpdateProductionOrder,
} from "./useProduction";

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

/** The harness collects a query the moment nothing observes it (gcTime 0);
 *  with no component mounted, the per-key override keeps a seeded one alive. */
const seed = (key: readonly unknown[]) => {
  client.setQueryDefaults(key, { gcTime: Infinity });
  client.setQueryData(key, {});
};

beforeEach(() => {
  client = new QueryClient();
});

const order = { id: "o1" };
const draft = { output_template_id: "t1", batches: "2" } as never;

/**
 * A production run is created, changed, completed, cancelled and reversed
 * through one endpoint each. A swapped verb or path completes a run the
 * operator meant to cancel, and a run that writes stock but forgets to refresh
 * the stock screens leaves them showing yesterday's quantities.
 */
describe("production reads", () => {
  it.each([
    [
      "useProductionOrders",
      () => useProductionOrders({ status: "completed", limit: 5 } as never),
      "/maker/production/orders",
      { status: "completed", limit: "5" },
    ],
    [
      "useProductionOrder",
      () => useProductionOrder("o1"),
      "/maker/production/orders/o1",
      {},
    ],
    [
      "useOrderStockMoves",
      () => useOrderStockMoves("o1"),
      "/maker/production/orders/o1/stock-moves",
      {},
    ],
    [
      "useMakerMonthlyResult",
      () => useMakerMonthlyResult(3),
      "/maker/production/monthly-result",
      { months: "3" },
    ],
  ])("%s asks %s", async (_name, hook, path, query) => {
    const log = recordRequests(() => []);
    renderHook(hook as () => unknown, { wrapper });
    await waitFor(() => expect(log.length).toBeGreaterThan(0));
    expect(log[0]).toMatchObject({ method: "GET", path, query });
  });

  it.each([
    ["useProductionOrder", () => useProductionOrder(undefined)],
    ["useOrderStockMoves", () => useOrderStockMoves(undefined)],
    ["useProductionPreview", () => useProductionPreview(null)],
  ])("%s waits until a run is named", async (_name, hook) => {
    const log = recordRequests();
    const { result } = renderHook(hook as () => { fetchStatus: string }, {
      wrapper,
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(log).toHaveLength(0);
  });

  it("previews the run the sheet describes", async () => {
    const log = recordRequests(() => ({ shortages: [] }));
    renderHook(() => useProductionPreview(draft), { wrapper });
    await waitFor(() => expect(log).toHaveLength(1));
    expect(log[0]).toMatchObject({
      method: "POST",
      path: "/maker/production/orders/preview",
      body: draft,
    });
  });
});

describe("production writes", () => {
  type Case = [
    string,
    () => { mutateAsync: (vars: never) => Promise<unknown> },
    unknown,
    { method: string; path: string; body?: unknown },
  ];
  const cases: Case[] = [
    [
      "useCreateProductionOrder",
      useCreateProductionOrder,
      draft,
      { method: "POST", path: "/maker/production/orders", body: draft },
    ],
    [
      "useRecordMadeProduction",
      useRecordMadeProduction,
      draft,
      { method: "POST", path: "/maker/production/orders/made", body: draft },
    ],
    [
      "useAddShortagesToShoppingList",
      useAddShortagesToShoppingList,
      draft,
      {
        method: "POST",
        path: "/maker/production/orders/shortages/shopping-list",
        body: draft,
      },
    ],
    [
      "useUpdateProductionOrder",
      () => useUpdateProductionOrder(),
      { orderId: "o1", data: { notes: "x" } },
      {
        method: "PATCH",
        path: "/maker/production/orders/o1",
        body: { notes: "x" },
      },
    ],
    [
      "useDuplicateProductionOrder",
      useDuplicateProductionOrder,
      "o1",
      { method: "POST", path: "/maker/production/orders/o1/duplicate" },
    ],
    [
      "useCompleteProduction",
      useCompleteProduction,
      { orderId: "o1", data: { actual_qty: "3" } },
      {
        method: "POST",
        path: "/maker/production/orders/o1/complete",
        body: { actual_qty: "3" },
      },
    ],
    [
      "useCancelProduction with a reason",
      useCancelProduction,
      { orderId: "o1", reason: "spoiled" },
      {
        method: "POST",
        path: "/maker/production/orders/o1/cancel",
        body: { reason: "spoiled" },
      },
    ],
    [
      "useReverseProduction",
      useReverseProduction,
      "o1",
      { method: "POST", path: "/maker/production/orders/o1/reverse" },
    ],
    [
      "useStartProduction",
      useStartProduction,
      { orderId: "o1", data: { started_on: "2026-11-10" } },
      {
        method: "POST",
        path: "/maker/production/orders/o1/start",
        body: { started_on: "2026-11-10" },
      },
    ],
    [
      "useAddPortion",
      useAddPortion,
      { orderId: "o1", data: { qty: "2", output_lot_name: "B1" } },
      {
        method: "POST",
        path: "/maker/production/orders/o1/portions",
        body: { qty: "2", output_lot_name: "B1" },
      },
    ],
    [
      "useFinishProduction",
      useFinishProduction,
      { orderId: "o1", data: { actual_qty: "4", finished_on: "2026-11-12" } },
      {
        method: "POST",
        path: "/maker/production/orders/o1/finish",
        body: { actual_qty: "4", finished_on: "2026-11-12" },
      },
    ],
    [
      "useTickStep",
      useTickStep,
      { orderId: "o1", index: 1, doneOn: "2026-11-11" },
      {
        method: "PUT",
        path: "/maker/production/orders/o1/steps/1",
        body: { done_on: "2026-11-11" },
      },
    ],
  ];

  it.each(cases)(
    "%s sends the request its button promised",
    async (_n, hook, vars, expected) => {
      const log = recordRequests(() => order);
      const { result } = renderHook(hook, { wrapper });
      await act(() => result.current.mutateAsync(vars as never));
      expect(log).toHaveLength(1);
      expect(log[0]).toMatchObject(expected);
    },
  );

  it("cancels with an empty body, not a reason, when none is given", async () => {
    const log = recordRequests(() => order);
    const { result } = renderHook(() => useCancelProduction(), { wrapper });
    await act(() => result.current.mutateAsync({ orderId: "o1" }));
    expect(log[0].body).toEqual({});
  });

  it.each([
    ["completing", () => useCompleteProduction(), { orderId: "o1" }],
    ["recording a run made", () => useRecordMadeProduction(), draft],
    ["reversing", () => useReverseProduction(), "o1"],
    ["starting", () => useStartProduction(), { orderId: "o1" }],
    [
      "putting a portion of",
      () => useAddPortion(),
      { orderId: "o1", data: { qty: "1" } },
    ],
    ["finishing", () => useFinishProduction(), { orderId: "o1" }],
  ])(
    "%s a run refreshes the stock screens it wrote to",
    async (_n, hook, vars) => {
      recordRequests(() => order);
      seed(queryKeys.stockQuants.all);
      const { result } = renderHook(
        hook as () => { mutateAsync: (v: never) => Promise<unknown> },
        { wrapper },
      );
      await act(() => result.current.mutateAsync(vars as never));
      expect(
        client.getQueryState(queryKeys.stockQuants.all)?.isInvalidated,
      ).toBe(true);
    },
  );

  it("refreshes the stock screens when a run that took ingredients is cancelled", async () => {
    recordRequests(() => ({ id: "o1", material_cost: "12.00" }));
    seed(queryKeys.stockQuants.all);
    const { result } = renderHook(() => useCancelProduction(), { wrapper });
    await act(() => result.current.mutateAsync({ orderId: "o1" }));
    expect(client.getQueryState(queryKeys.stockQuants.all)?.isInvalidated).toBe(
      true,
    );
  });

  it("leaves the stock screens alone when a run is only cancelled", async () => {
    recordRequests(() => order);
    seed(queryKeys.stockQuants.all);
    const { result } = renderHook(() => useCancelProduction(), { wrapper });
    await act(() => result.current.mutateAsync({ orderId: "o1" }));
    expect(client.getQueryState(queryKeys.stockQuants.all)?.isInvalidated).toBe(
      false,
    );
  });
});
