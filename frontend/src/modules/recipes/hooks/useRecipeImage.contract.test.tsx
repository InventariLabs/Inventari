import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import { useDeleteRecipeImage, useUploadRecipeImage } from "./useRecipes";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// jsdom has no canvas, so the real compressor never settles.
vi.mock("@/lib/imageUtils", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/imageUtils")>()),
  prepareImageUpload: (file: File) => Promise.resolve(file),
}));

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient();
});

/**
 * A recipe's cover is on the cards of the list as well as on its own page: a
 * new or removed cover refreshes both, not the open recipe alone.
 */
describe("a recipe's cover", () => {
  it("refreshes the recipe lists when it is replaced", async () => {
    server.use(
      http.post("/api/v1/recipes/r1/image", () =>
        HttpResponse.json({ image_url: "/uploads/new.jpg" }),
      ),
    );
    client.setQueryData(queryKeys.recipes.all({ page: 1 }), { items: [] });
    const { result } = renderHook(() => useUploadRecipeImage(), { wrapper });

    await act(async () => {
      result.current.mutate({
        id: "r1",
        file: new File(["x"], "c.jpg", { type: "image/jpeg" }),
      });
    });

    await waitFor(() =>
      expect(
        client.getQueryState(queryKeys.recipes.all({ page: 1 }))?.isInvalidated,
      ).toBe(true),
    );
  });

  it("refreshes the recipe lists when it is removed", async () => {
    server.use(
      http.delete(
        "/api/v1/recipes/r1/image",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    client.setQueryData(queryKeys.recipes.all({ page: 1 }), { items: [] });
    const { result } = renderHook(() => useDeleteRecipeImage(), { wrapper });

    await act(async () => {
      result.current.mutate("r1");
    });

    await waitFor(() =>
      expect(
        client.getQueryState(queryKeys.recipes.all({ page: 1 }))?.isInvalidated,
      ).toBe(true),
    );
  });
});
