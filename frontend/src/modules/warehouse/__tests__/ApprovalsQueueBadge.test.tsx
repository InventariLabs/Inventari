import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { ApprovalsQueueBadge } from "../components/ApprovalsQueueBadge";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

// Mutable holder so individual tests can flip the approvals module on/off.
const state = vi.hoisted(() => ({ approvalsEnabled: true }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    isModuleEnabled: (m: string) => m === "approvals" && state.approvalsEnabled,
  }),
}));

beforeEach(() => {
  state.approvalsEnabled = true;
  vi.clearAllMocks();
  server.resetHandlers();
});

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("ApprovalsQueueBadge", () => {
  it("renders the pending count when approvals is enabled and count > 0", async () => {
    server.use(
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({
          documents: [{ id: "d1" }, { id: "d2" }],
          total: 2,
        }),
      ),
    );
    render(<ApprovalsQueueBadge />, { wrapper: createWrapper() });
    expect(
      await screen.findByTestId("approvals-queue-badge"),
    ).toHaveTextContent("2");
  });

  it("fills with the button pair, not the 600 step white text fails on", async () => {
    // 10 px white on primary-600 was 3.77:1 under the Food & Home palette;
    // the shared Button fills at 700, and 800 in dark.
    server.use(
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({ documents: [{ id: "d1" }], total: 1 }),
      ),
    );
    render(<ApprovalsQueueBadge />, { wrapper: createWrapper() });
    const badge = await screen.findByTestId("approvals-queue-badge");
    expect(badge).toHaveClass("bg-primary-700", "dark:bg-primary-800");
    expect(badge).not.toHaveClass("bg-primary-600");
  });

  it("renders nothing when the queue is empty", async () => {
    server.use(
      http.get("/api/v1/warehouse/awaiting-my-approval", () =>
        HttpResponse.json({ documents: [], total: 0 }),
      ),
    );
    render(<ApprovalsQueueBadge />, { wrapper: createWrapper() });
    await waitFor(() =>
      expect(screen.queryByTestId("approvals-queue-badge")).toBeNull(),
    );
  });

  it("renders nothing and does not fetch when the approvals module is disabled", async () => {
    state.approvalsEnabled = false;
    const handler = vi.fn(() =>
      HttpResponse.json({ documents: [{ id: "d1" }], total: 1 }),
    );
    server.use(http.get("/api/v1/warehouse/awaiting-my-approval", handler));
    render(<ApprovalsQueueBadge />, { wrapper: createWrapper() });
    await waitFor(() =>
      expect(screen.queryByTestId("approvals-queue-badge")).toBeNull(),
    );
    expect(handler).not.toHaveBeenCalled();
  });
});
