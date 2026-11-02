import React from "react";
import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useAssignWorkItem,
  useCreateCustomWorkItem,
  useDeleteCustomWorkItem,
  usePostReplenishmentProposal,
  useReplenishmentProposal,
  useSetCustomWorkItemDone,
  useStartCount,
  useWorkMeasures,
} from "./useWorkItems";

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["warehouse"],
    isModuleEnabled: (name: string) => name === "warehouse",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidated: unknown[] = [];
  vi.spyOn(client, "invalidateQueries").mockImplementation(async (filters) => {
    invalidated.push(filters?.queryKey);
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { invalidated, wrapper };
}

interface Seen {
  call: string;
  body: unknown;
}

function record(reply: JsonBodyType = {}) {
  const seen: Seen[] = [];
  server.use(
    http.all("*/api/v1/*", async ({ request }) => {
      const url = new URL(request.url);
      const text = request.method === "GET" ? "" : await request.text();
      seen.push({
        call: `${request.method} ${url.pathname.replace(/^.*\/api\/v1/, "")}${url.search}`,
        body: text ? JSON.parse(text) : null,
      });
      return HttpResponse.json(reply);
    }),
  );
  return seen;
}

/**
 * The work board's task actions. A task action that did not refresh the
 * documents left the card in its old column; a replenishment move that did
 * not drop the alerts kept offering a shortage that was already filled.
 */
describe("work item actions — the task is changed and the board refreshed", () => {
  it("claims a task only while it is free, and refreshes the board", async () => {
    const seen = record();
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => useAssignWorkItem(), { wrapper });

    await act(() =>
      result.current.mutateAsync({
        sourceKind: "document",
        sourceId: "doc-1",
        assigneeId: "u-1",
        onlyIfUnassigned: true,
      }),
    );

    expect(seen).toEqual([
      {
        call: "PUT /warehouse/work-items/document/doc-1/assignee",
        body: { assignee_id: "u-1", only_if_unassigned: true },
      },
    ]);
    expect(invalidated).toContainEqual(queryKeys.documents.all);
  });

  it("starts a scheduled count", async () => {
    const seen = record({ id: "st-1" });
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => useStartCount(), { wrapper });

    await expect(
      act(() => result.current.mutateAsync("sch-1")),
    ).resolves.toEqual({ id: "st-1" });
    expect(seen[0].call).toBe(
      "POST /stock-takes/cycle-count-schedules/sch-1/run",
    );
    expect(invalidated).toContainEqual(queryKeys.documents.all);
  });

  it("adds, ticks off and removes a task of the reader's own", async () => {
    const seen = record({ id: "ci-1" });
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(
      () => ({
        create: useCreateCustomWorkItem(),
        done: useSetCustomWorkItemDone(),
        remove: useDeleteCustomWorkItem(),
      }),
      { wrapper },
    );

    await act(() => result.current.create.mutateAsync({ title: "Label bins" }));
    await act(() =>
      result.current.done.mutateAsync({ id: "ci-1", done: true }),
    );
    await act(() => result.current.remove.mutateAsync("ci-1"));

    expect(seen).toEqual([
      {
        call: "POST /warehouse/work-items/custom",
        body: { title: "Label bins" },
      },
      {
        call: "PUT /warehouse/work-items/custom/ci-1/done",
        body: { done: true },
      },
      { call: "DELETE /warehouse/work-items/custom/ci-1", body: null },
    ]);
    expect(
      invalidated.filter(
        (key) =>
          JSON.stringify(key) === JSON.stringify(queryKeys.documents.all),
      ),
    ).toHaveLength(3);
  });

  it("posts a replenishment proposal and drops the alerts that raised it", async () => {
    const seen = record({ document_id: "doc-2" });
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => usePostReplenishmentProposal(), {
      wrapper,
    });

    await act(() =>
      result.current.mutateAsync({ ruleId: "rule-1", scannedCode: "R-1" }),
    );

    expect(seen[0].call).toBe(
      "POST /purchase-orders/replenishment/proposals/rule-1/move?scanned_code=R-1",
    );
    expect(invalidated).toContainEqual(
      queryKeys.purchaseOrders.replenishmentAlerts(),
    );
    expect(invalidated).toContainEqual(queryKeys.storages.all);
  });
});

describe("work item reads", () => {
  it("reads the week's measures for the strip above the board", async () => {
    record({ dock_to_stock_hours: 4 });
    const { wrapper } = setup();
    const { result } = renderHook(() => useWorkMeasures(), { wrapper });

    await waitFor(() =>
      expect(result.current.data).toEqual({ dock_to_stock_hours: 4 }),
    );
  });

  it("reads the proposal a replenishment rule makes", async () => {
    const seen = record({ rule_id: "rule-4", lines: [] });
    const { wrapper } = setup();
    const { result } = renderHook(() => useReplenishmentProposal("rule-4"), {
      wrapper,
    });

    await waitFor(() =>
      expect(result.current.data).toEqual({ rule_id: "rule-4", lines: [] }),
    );
    expect(seen[0].call).toBe(
      "GET /purchase-orders/replenishment/proposals/rule-4",
    );
  });
});
