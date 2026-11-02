import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useEquipmentAsset } from "./useEquipmentAssets";

const ITEM_ID = "11111111-1111-1111-1111-111111111111";

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe("useEquipmentAsset", () => {
  it("asks for the archived record so the card survives the archive", async () => {
    // The card outlives the archive — Restore and Purge live under it and
    // assignment history keeps linking to it — so the read names the
    // archive. Without the ask the endpoint answers the archive-pointing
    // 404 and the page has nothing to render.
    server.use(
      http.get("*/items/:id", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("include_archived") !== "true") {
          return HttpResponse.json(
            {
              detail: {
                code: "ITEM_ARCHIVED",
                message:
                  "Item is archived and can be restored from the archive",
              },
            },
            { status: 404 },
          );
        }
        return HttpResponse.json({
          id: ITEM_ID,
          name: "Archived Laptop",
          is_deleted: true,
        });
      }),
    );

    const { result } = renderHook(() => useEquipmentAsset(ITEM_ID), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.is_deleted).toBe(true);
    expect(result.current.data?.name).toBe("Archived Laptop");
  });
});
