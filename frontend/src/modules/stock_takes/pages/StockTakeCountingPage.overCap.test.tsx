import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useState, type ReactNode } from "react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import StockTakeCountingPage from "./StockTakeCountingPage";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

import { signInWith } from "@/test/auth";
import { onePage } from "@/test/mocks/page";

// The page asks whether this account may write before it renders the
// form at all; rendering it signed out tests the denial instead. Accepting a
// count above the cap is `stock_takes:approve`, which the server checks on
// the override — the page now asks before offering the decision.
beforeEach(() => {
  signInWith(["stock_takes:write", "stock_takes:approve"]);
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

type HeaderData = { actions?: ReactNode };

/**
 * The page hands its actions to the shell header, so a test that only mocks
 * `setHeader` can never click them. This host renders what the page registers.
 */
function HeaderHost({ children }: { children: ReactNode }) {
  const [header, setHeader] = useState<HeaderData>({});
  const stableSetHeader = useCallback((data: HeaderData) => {
    setHeader(data);
  }, []);
  return (
    <PageHeaderContext.Provider
      value={{ data: header, setHeader: stableSetHeader }}
    >
      {header.actions}
      {children}
    </PageHeaderContext.Provider>
  );
}

/**
 * A count far above the system stock used to be rewritten in silence — the
 * item ended at five times its old quantity while the report confirmed the
 * number that was counted. Now the posting is held back and the person who
 * counted decides.
 */
describe("StockTakeCountingPage — a count above the growth cap", () => {
  let queryClient: QueryClient;
  let completeBodies: Record<string, unknown>[];

  const renderPage = () =>
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <HeaderHost>
                  <StockTakeCountingPage />
                </HeaderHost>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    completeBodies = [];
    server.use(
      http.get("/api/v1/stock-takes/1", () =>
        HttpResponse.json({
          id: "1",
          name: "Stock Take 1",
          location_id: "1",
          location_name: "Fridge",
          status: "in_progress",
          items_count: 1,
          items: [
            {
              id: "sti-1",
              item_id: "1",
              name: "Wheat bread 700g",
              system_quantity: 2,
              counted_quantity: 20,
            },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
      http.get("/api/v1/locations/1/items", () =>
        HttpResponse.json(
          onePage([{ id: "1", name: "Wheat bread 700g", quantity: 2 }]),
        ),
      ),
      http.post("/api/v1/stock-takes/1/complete", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        completeBodies.push(body);
        if (body.force_over_cap) {
          return HttpResponse.json({ stock_take_id: "1" });
        }
        return HttpResponse.json(
          {
            detail: {
              code: "STOCK_TAKE_OVER_CAP",
              message: "1 counted quantity is far above the system stock.",
              over_cap_items: [
                {
                  item_id: "1",
                  item_name: "Wheat bread 700g",
                  system_quantity: 2,
                  counted_quantity: 20,
                  cap: 10,
                },
              ],
            },
          },
          { status: 409 },
        );
      }),
    );
  });

  it("asks about the rows the server refused, naming them", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Wheat bread 700g")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("stock-take-complete-btn"));
    await user.click(await screen.findByRole("button", { name: "Complete" }));

    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() =>
      expect(dialog).toHaveTextContent(/counted 20, system 2/),
    );
  });

  it("saves the counted number only after the count is accepted", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Wheat bread 700g")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("stock-take-complete-btn"));
    await user.click(await screen.findByRole("button", { name: "Complete" }));
    await user.click(
      await screen.findByRole("button", { name: "Save counted numbers" }),
    );

    await waitFor(() => expect(completeBodies).toHaveLength(2));
    expect(completeBodies[0].force_over_cap).toBe(false);
    expect(completeBodies[1].force_over_cap).toBe(true);
  });

  it("does not send anything when the overrun is not accepted", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Wheat bread 700g")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("stock-take-complete-btn"));
    await user.click(await screen.findByRole("button", { name: "Complete" }));
    await screen.findByRole("button", { name: "Save counted numbers" });
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Save counted numbers" }),
      ).not.toBeInTheDocument(),
    );
    expect(completeBodies).toHaveLength(1);
  });

  it("says how many products the posting will overwrite", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Wheat bread 700g")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("stock-take-complete-btn"));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/overwrites the stock of one product/);
  });
});
