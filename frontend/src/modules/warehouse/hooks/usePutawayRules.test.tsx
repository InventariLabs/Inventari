import React from "react";
import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useCreatePutawayRule,
  useDeletePutawayRule,
  useSetReceivingMode,
  useUnsilenceHomeShelf,
  useUpdatePutawayRule,
} from "./usePutawayRules";

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

function record(reply: JsonBodyType = { id: "rule-1" }) {
  const seen: string[] = [];
  server.use(
    http.all("*/api/v1/*", ({ request }) => {
      const url = new URL(request.url);
      seen.push(
        `${request.method} ${url.pathname.replace(/^.*\/api\/v1/, "")}`,
      );
      return HttpResponse.json(reply);
    }),
  );
  return seen;
}

/**
 * A rule saved without dropping the rules cache left the rules page listing
 * the old set; a receiving-mode change that kept the locations cached hid the
 * receiving area it had just made.
 */
describe("putaway rule writes — each refreshes what it changed", () => {
  it("creates, updates and deletes a rule and refreshes the rules list each time", async () => {
    const seen = record();
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(
      () => ({
        create: useCreatePutawayRule(),
        update: useUpdatePutawayRule(),
        remove: useDeletePutawayRule(),
      }),
      { wrapper },
    );

    await act(() =>
      result.current.create.mutateAsync({ target_location_id: "l" } as never),
    );
    await act(() =>
      result.current.update.mutateAsync({
        id: "rule-1",
        data: { priority: 1 } as never,
      }),
    );
    await act(() => result.current.remove.mutateAsync("rule-1"));

    expect(seen).toEqual([
      "POST /warehouse/putaway-rules",
      "PUT /warehouse/putaway-rules/rule-1",
      "DELETE /warehouse/putaway-rules/rule-1",
    ]);
    expect(
      invalidated.filter(
        (key) =>
          JSON.stringify(key) ===
          JSON.stringify(queryKeys.documents.putawayRules),
      ),
    ).toHaveLength(3);
  });

  it("switches a warehouse's receiving and refreshes its modes and the locations", async () => {
    const seen = record({ warehouse_id: "wh-1" });
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => useSetReceivingMode(), { wrapper });

    await act(() =>
      result.current.mutateAsync({ warehouseId: "wh-1", twoStep: true }),
    );

    expect(seen).toEqual(["PUT /warehouse/putaway/receiving-modes/wh-1"]);
    expect(invalidated).toContainEqual(
      queryKeys.documents.putawayReceivingModes,
    );
    expect(invalidated).toContainEqual(queryKeys.storages.all);
  });

  it("un-silences a product's home location and refreshes the silenced list", async () => {
    const seen = record();
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => useUnsilenceHomeShelf(), { wrapper });

    await act(() => result.current.mutateAsync("pt-1"));

    expect(seen).toEqual([
      "DELETE /warehouse/putaway/home-shelf/silenced/pt-1",
    ]);
    expect(invalidated).toEqual([queryKeys.documents.putawayHomeSilenced]);
  });
});
