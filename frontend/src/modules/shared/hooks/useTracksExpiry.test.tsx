/**
 * The expiry decision: a location that watches expiry, or a record that
 * carries a date — the latter answered by the statistics overview only while
 * the stats module is on.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import * as React from "react";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { useTracksExpiry } from "./useTracksExpiry";

let overviewAsked = 0;
let typesAsked = 0;

function serve(modules: string[], tracksExpiry: boolean) {
  server.use(
    http.get("/api/v1/modules/my", () => HttpResponse.json(modules)),
    // No location kind watches expiry, so only the records can say yes.
    http.get("/api/v1/location-types", () => {
      typesAsked += 1;
      return HttpResponse.json(onePage([]));
    }),
    http.get("/api/v1/stats/overview", () => {
      overviewAsked += 1;
      return HttpResponse.json({ tracks_expiry: tracksExpiry });
    }),
  );
}

function renderDecision() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderHook(() => useTracksExpiry(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>
        <ModulesProvider>{children}</ModulesProvider>
      </QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  overviewAsked = 0;
  typesAsked = 0;
  useAuthStore.setState({ isAuthenticated: true, isLoading: false });
});

describe("useTracksExpiry", () => {
  it("says yes when the records carry dates, as the overview reports", async () => {
    serve(["core", "items", "locations", "stats"], true);
    const { result } = renderDecision();
    await waitFor(() => expect(result.current).toBe(true));
  });

  it("asks the overview nothing while the stats module is off", async () => {
    serve(["core", "items", "locations"], true);
    const { result } = renderDecision();
    await waitFor(() => expect(typesAsked).toBeGreaterThan(0));
    // Let the module list and the locations' answer settle before asserting.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
    expect(result.current).toBe(false);
    expect(overviewAsked).toBe(0);
  });
});
