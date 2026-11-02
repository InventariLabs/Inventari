/**
 * A movement trail names its document sources by number, asked of the
 * warehouse register in one request for the rows on screen.
 */
import { describe, it, expect } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import * as React from "react";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { useDocumentNumbers } from "./useDocumentNumbers";

function renderNumbers(ids: (string | null)[], enabled = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderHook(() => useDocumentNumbers(ids, enabled), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

describe("useDocumentNumbers", () => {
  it("asks for the page's documents by repeated id and names each by number", async () => {
    let asked: string[] = [];
    server.use(
      http.get("/api/v1/warehouse/documents", ({ request }) => {
        asked = new URL(request.url).searchParams.getAll("ids");
        return HttpResponse.json(
          onePage([
            { id: "doc-1", number: "IN/2026/0001" },
            { id: "doc-2", number: "OUT/2026/0007" },
          ]),
        );
      }),
    );

    const { result } = renderNumbers(["doc-2", null, "doc-1", "doc-2"]);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(asked).toEqual(["doc-1", "doc-2"]);
    expect(result.current.data).toEqual({
      "doc-1": "IN/2026/0001",
      "doc-2": "OUT/2026/0007",
    });
  });

  it("asks nothing while the register is not there to answer", () => {
    const { result } = renderNumbers(["doc-1"], false);
    expect(result.current.fetchStatus).toBe("idle");
  });
});
