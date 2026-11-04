import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { recordRequests } from "@/test/requestLog";
import { onePage } from "@/test/mocks/page";
import {
  useBulkLinkIngredients,
  useSuggestIngredientMatches,
  useUnlinkedIngredients,
} from "./useIngredientLinking";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({ isLoading: false, isModuleEnabled: () => true }),
}));

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient();
});

/** Linking the backlog of free-text ingredients to products is three calls. */
describe("ingredient linking hooks", () => {
  it("reads the unlinked backlog", async () => {
    const log = recordRequests(() => onePage([{ id: "g1", name: "flour" }]));
    const { result } = renderHook(() => useUnlinkedIngredients(), { wrapper });
    await waitFor(() =>
      expect(result.current.data).toEqual({
        items: [{ id: "g1", name: "flour" }],
        hasIngredients: true,
      }),
    );
    expect(log[0].path).toBe("/recipes/ingredients/unlinked");
  });

  it("asks for match proposals with a POST and keeps nothing server-side", async () => {
    const log = recordRequests(() => ({ proposals: [] }));
    const { result } = renderHook(() => useSuggestIngredientMatches(), {
      wrapper,
    });
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync();
    });
    expect(answer).toEqual({ proposals: [] });
    expect(log[0]).toMatchObject({
      method: "POST",
      path: "/recipes/ingredients/match-proposals",
    });
  });

  it("sends the approved links as one batch", async () => {
    const log = recordRequests(() => ({ linked: 2 }));
    const links = [
      { ingredient_id: "g1", template_id: "t1" },
      { ingredient_id: "g2", template_id: "t2" },
    ];
    const { result } = renderHook(() => useBulkLinkIngredients(), { wrapper });
    await act(() => result.current.mutateAsync(links as never));
    expect(log).toHaveLength(1);
    expect(log[0]).toMatchObject({
      method: "POST",
      path: "/recipes/ingredients/link-templates",
      body: { links },
    });
  });
});
