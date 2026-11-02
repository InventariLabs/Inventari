import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { useSeedDefaultTemplates } from "@/modules/shared/hooks/useDocumentTemplates";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

/**
 * Copying the built-in layouts is idempotent, and the screen used to report
 * the request rather than the answer: pressed a second time it said the
 * layouts had been copied while the server had copied nothing and answered
 * with an empty list. Somebody who deleted their own copy and wants it back
 * is the one this misleads — they go looking for a row that was never made.
 */
const wrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

const template = (id: string) => ({
  id,
  organization_id: "org-1",
  name: `Layout ${id}`,
  template_type: "STANDARD",
  html_body: "<p></p>",
  is_default: false,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
});

beforeEach(() => {
  vi.clearAllMocks();
  server.resetHandlers();
});

describe("useSeedDefaultTemplates", () => {
  it("counts what was copied", async () => {
    server.use(
      http.post("/api/v1/warehouse/templates/seed-defaults", () =>
        HttpResponse.json([template("a"), template("b")], { status: 201 }),
      ),
    );

    const { result } = renderHook(() => useSeedDefaultTemplates("warehouse"), {
      wrapper: wrapper(),
    });
    result.current.mutate();

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(vi.mocked(toast.success).mock.calls[0]?.[0]).toContain("2");
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("says the layouts were already there when it copied nothing", async () => {
    server.use(
      http.post("/api/v1/equipment/templates/seed-defaults", () =>
        HttpResponse.json([], { status: 201 }),
      ),
    );

    const { result } = renderHook(() => useSeedDefaultTemplates("equipment"), {
      wrapper: wrapper(),
    });
    result.current.mutate();

    await waitFor(() => expect(toast.info).toHaveBeenCalled());
    expect(vi.mocked(toast.info).mock.calls[0]?.[0]).toBe(
      "Nothing to copy — every built-in layout is already here as your own.",
    );
    expect(toast.success).not.toHaveBeenCalled();
  });
});
