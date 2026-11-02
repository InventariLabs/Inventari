import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import StorageWizard from "./StorageWizard";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * The wizard offers every existing location as a parent. When the list did
 * not arrive the picker used to vanish without a word, and the first step
 * read as an organization that has nothing yet.
 */
describe("StorageWizard — the locations did not load", () => {
  it("says so with a retry, and the retry asks again", async () => {
    let asked = 0;
    server.use(
      http.get("/api/v1/locations", () => {
        asked += 1;
        return HttpResponse.json({ detail: "boom" }, { status: 500 });
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <MemoryRouter>
            <StorageWizard isOpen onClose={vi.fn()} />
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>,
    );

    const retry = await screen.findByRole("button", { name: /try again/i });
    const before = asked;
    await userEvent.click(retry);
    await vi.waitFor(() => expect(asked).toBeGreaterThan(before));
  });
});
