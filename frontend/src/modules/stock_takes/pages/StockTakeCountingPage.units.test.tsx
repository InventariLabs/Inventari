import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import StockTakeCountingPage from "./StockTakeCountingPage";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { signInWith } from "@/test/auth";
import { onePage } from "@/test/mocks/page";

// The page asks whether this account may write before it renders the
// form at all; rendering it signed out tests the denial instead.
beforeEach(() => {
  signInWith(["stock_takes:write"]);
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * The screen where somebody types a quantity, and the unit that quantity is
 * in.
 *
 * Bananas are weighed and yoghurt is counted, and the card said neither: the
 * field read itself with `parseInt`, so 2.1 kg became 2 kg before anything
 * left the browser — and the truncation carried the row across the tolerance,
 * turning a difference nobody would explain into one the screen demanded a
 * reason for.
 */
describe("StockTakeCountingPage — counting in the row's own unit", () => {
  let queryClient: QueryClient;
  let counted: Record<string, unknown>[];

  const renderPage = () =>
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: () => {} }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

  const cardFor = (name: string): HTMLElement => {
    const heading = screen.getByText(name);
    const card = heading.closest("[data-testid='stock-take-item-card']");
    if (!card) throw new Error(`no card for ${name}`);
    return card as HTMLElement;
  };

  const fieldOn = (name: string): HTMLElement =>
    within(cardFor(name)).getByRole("textbox", { name: /counted quantity/i });

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    counted = [];
    vi.mocked(toast.error).mockClear();
    server.use(
      http.get("/api/v1/stock-takes/1", () =>
        HttpResponse.json({
          id: "1",
          name: "Stock Take 1",
          location_id: "1",
          location_name: "Fridge",
          status: "in_progress",
          tolerance_percent: 10,
          items_count: 2,
          items: [
            {
              id: "sti-1",
              item_id: "1",
              item_name: "Bananas",
              uom_symbol: "kg",
              uom_rounding: "0.001000",
              system_quantity: "2.300",
              counted_quantity: null,
              is_discrepancy: 0,
              counts: [],
            },
            {
              id: "sti-2",
              item_id: "2",
              item_name: "Yoghurt",
              uom_symbol: "pcs",
              uom_rounding: "1.000000",
              system_quantity: "5.000",
              counted_quantity: null,
              is_discrepancy: 0,
              counts: [],
            },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
      http.get("/api/v1/locations/1/items", () =>
        HttpResponse.json(
          onePage([
            { id: "1", name: "Bananas", quantity: 2.3 },
            { id: "2", name: "Yoghurt", quantity: 5 },
          ]),
        ),
      ),
      http.patch(
        "/api/v1/stock-takes/1/items/:lineId/count",
        async ({ request }) => {
          counted.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({});
        },
      ),
    );
  });

  it("tells a weighed row from a counted one without opening anything", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Bananas")).toBeInTheDocument(),
    );

    const weighed = within(cardFor("Bananas"));
    expect(weighed.getByText("2.3 kg")).toBeInTheDocument();
    expect(
      weighed.getByRole("button", { name: "One more kg of Bananas" }),
    ).toBeInTheDocument();

    const counted = within(cardFor("Yoghurt"));
    // "pcs." is what the unit catalogue calls the symbol on the record; the
    // card used to append the symbol itself and read "5 pcs".
    expect(counted.getByText("5 pcs.")).toBeInTheDocument();
    // The step button says "pcs." too, so the announcement matches the figure
    // it steps: "One more pcs of Yoghurt" was the record's spelling read out
    // loud beside a resolved one.
    expect(
      counted.getByRole("button", { name: "One more pcs. of Yoghurt" }),
    ).toBeInTheDocument();
  });

  it("gives the note field a name of its own", async () => {
    // The count field had an accessible name and the note beside it did not:
    // one row, two boxes, and only one of them announced itself.
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Bananas")).toBeInTheDocument(),
    );

    expect(
      within(cardFor("Bananas")).getByRole("textbox", {
        name: "Note about Bananas",
      }),
    ).toBeInTheDocument();
  });

  it("states the difference as a number, not as a binary remainder", async () => {
    // 2.300 minus 2 is −0.3, and the card printed "(-0.2999999999999998)" —
    // on the row somebody copies onto a slip of paper.
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
              item_name: "Bananas",
              uom_symbol: "kg",
              uom_rounding: "0.001000",
              system_quantity: "2.300",
              counted_quantity: "2.000",
              is_discrepancy: 1,
              counts: [],
            },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Bananas")).toBeInTheDocument(),
    );

    const card = within(cardFor("Bananas"));
    // The gap carries the row's unit now, like the two figures it is the gap
    // between — and like the report badge beside it always has.
    expect(card.getByText("(-0.3 kg)")).toBeInTheDocument();
  });

  it("keeps the decimal a weighed row is allowed", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Bananas")).toBeInTheDocument(),
    );

    const field = fieldOn("Bananas");
    await user.clear(field);
    await user.type(field, "2.1");

    expect(field).toHaveValue("2.1");
  });

  it("sends the decimal to the server rather than a rounded stand-in", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Bananas")).toBeInTheDocument(),
    );

    const card = cardFor("Bananas");
    await user.clear(fieldOn("Bananas"));
    await user.type(fieldOn("Bananas"), "2.1");
    await user.click(
      within(card).getByRole("button", { name: /save the count/i }),
    );

    await waitFor(() => expect(counted).toHaveLength(1));
    expect(counted[0].counted_quantity).toBe(2.1);
  });

  it("leaves a difference inside the tolerance where the counter put it", async () => {
    // The sharper half of the truncation: 2.1 against 2.300 is −8.7% and sits
    // inside a tolerance of 10%; 2 against 2.300 is −13% and does not. Cutting
    // the decimal in the field therefore invented a discrepancy and demanded a
    // reason for it. What the row sends is what decides, so this is the
    // assertion that keeps the threshold where the stock take put it.
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Bananas")).toBeInTheDocument(),
    );

    const card = cardFor("Bananas");
    await user.clear(fieldOn("Bananas"));
    await user.type(fieldOn("Bananas"), "2.1");
    await user.click(
      within(card).getByRole("button", { name: /save the count/i }),
    );

    await waitFor(() => expect(counted).toHaveLength(1));
    const sent = Number(counted[0].counted_quantity);
    const expected = 2.3;
    const tolerance = expected * 0.1;
    expect(Math.abs(sent - expected)).toBeLessThanOrEqual(tolerance);
    expect(Math.abs(Math.trunc(sent) - expected)).toBeGreaterThan(tolerance);
  });

  it("refuses a fraction of something counted in pieces, and names the unit", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Yoghurt")).toBeInTheDocument(),
    );

    const card = cardFor("Yoghurt");
    await user.clear(fieldOn("Yoghurt"));
    await user.type(fieldOn("Yoghurt"), "3.5");
    await user.click(
      within(card).getByRole("button", { name: /save the count/i }),
    );

    expect(counted).toHaveLength(0);
    const said = vi.mocked(toast.error).mock.calls;
    // The catalogue's word, dot and all — "pcs" alone would pass the way the
    // raw symbol did, and this assertion exists to tell the two apart.
    expect(String(said[said.length - 1][0])).toContain("pcs.");
  });
});
