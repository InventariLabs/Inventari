import { withLanguage } from "@/test/mocks/i18n";
import React from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useCompleteStockTakeFlow } from "./useCompleteStockTakeFlow";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import { useAuthStore } from "@/store/authStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { queryKeys } from "@/hooks/queries/keys";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const lines = [
  {
    id: "sti-1",
    item_id: "item-1",
    item_name: "Milk",
    system_quantity: 2,
    counted_quantity: 2,
  },
] as unknown as StockTakeItem[];

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })
    }
  >
    <BrowserRouter>{children}</BrowserRouter>
  </QueryClientProvider>
);

describe("useCompleteStockTakeFlow", () => {
  let asked: { message?: string }[];
  const confirm = vi.fn(async (options: { message?: string }) => {
    asked.push(options);
    return false;
  });

  beforeEach(() => {
    asked = [];
    confirm.mockClear();
    server.use(
      http.post("/api/v1/stock-takes/1/complete", () => HttpResponse.json({})),
    );
  });

  // Completing is the last moment anyone can go back for a number still
  // sitting in its box, and a stock take with "require full count" set
  // refuses to close over exactly those rows with nothing on the screen
  // saying which ones.
  it("names the counts still waiting in their boxes", async () => {
    const { result } = renderHook(
      () => useCompleteStockTakeFlow("1", lines, confirm, 3),
      { wrapper },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    await waitFor(() => expect(asked.length).toBe(1));
    expect(asked[0].message).toContain(
      "3 counted numbers have not been saved and will be lost.",
    );
  });

  // "Require full count" refuses the close on every line without a number.
  // The refusal used to come after the confirmation, so the dialog offered
  // Complete and a toast then took it back.
  it("refuses before asking when a full count is required and lines are open", async () => {
    const open = [
      ...lines,
      {
        ...lines[0],
        id: "sti-2",
        item_id: "item-2",
        item_name: "Bread",
        counted_quantity: null,
      },
      {
        ...lines[0],
        id: "sti-3",
        item_id: "item-3",
        item_name: "Eggs",
        counted_quantity: null,
      },
    ] as unknown as StockTakeItem[];
    const { result } = renderHook(
      () => useCompleteStockTakeFlow("1", open, confirm, 0, true),
      { wrapper },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    expect(confirm).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("2 products are still uncounted"),
    );
  });

  // A read that has just returned reaches the query cache before it reaches
  // the screen. A press in between must judge the saved count, not the rows
  // of the render before it.
  it("judges the rows the cache holds, not the ones last drawn", async () => {
    vi.mocked(toast.error).mockClear();
    const drawn = [{ ...lines[0], counted_quantity: null }] as StockTakeItem[];
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    client.setQueryData(queryKeys.stockTakes.detail("1"), { items: lines });
    const { result } = renderHook(
      () => useCompleteStockTakeFlow("1", drawn, confirm, 0, true),
      {
        wrapper: ({ children }: { children: React.ReactNode }) => (
          <QueryClientProvider client={client}>
            <BrowserRouter>{children}</BrowserRouter>
          </QueryClientProvider>
        ),
      },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    expect(toast.error).not.toHaveBeenCalled();
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("counts products, not records, and says when numbers are only unsaved", async () => {
    // Two records of one product are one product to the reader; and a number
    // still in its box is a Save away, which the refusal has to say.
    const open = [
      ...lines,
      { ...lines[0], id: "sti-2", item_id: "item-2", counted_quantity: null },
      { ...lines[0], id: "sti-3", item_id: "item-3", counted_quantity: null },
    ] as unknown as StockTakeItem[];
    const { result } = renderHook(
      () => useCompleteStockTakeFlow("1", open, confirm, 2, true),
      { wrapper },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    expect(confirm).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringMatching(
        /One product is still uncounted.*2 counted numbers have not been saved/,
      ),
    );
  });

  it("still asks when a partial count is allowed", async () => {
    const open = [
      ...lines,
      { ...lines[0], id: "sti-2", item_id: "item-2", counted_quantity: null },
    ] as unknown as StockTakeItem[];
    const { result } = renderHook(
      () => useCompleteStockTakeFlow("1", open, confirm, 0, false),
      { wrapper },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("says nothing about unsaved counts when there are none", async () => {
    const { result } = renderHook(
      () => useCompleteStockTakeFlow("1", lines, confirm, 0),
      { wrapper },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    await waitFor(() => expect(asked.length).toBe(1));
    expect(asked[0].message).not.toContain("not been saved");
  });

  // Found on another location, a unit agrees in number and still moves.
  it("counts a unit found away from its record among the changes", async () => {
    const moved = [
      { ...lines[0], expected_location_id: "shelf-1" },
    ] as unknown as StockTakeItem[];
    const { result } = renderHook(
      () => useCompleteStockTakeFlow("1", moved, confirm, 0),
      { wrapper },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    await waitFor(() => expect(asked.length).toBe(1));
    expect(asked[0].message).toContain("the stock of one product");
  });

  // Two receipts and a putaway into one place leave three records of one
  // cable; counted wrong, they are still one product being overwritten.
  it("counts the products overwritten, not the records they stand as", async () => {
    const cable = (id: string, system: number) => ({
      id: `sti-${id}`,
      item_id: id,
      item_name: "USB-C Cable 1m",
      system_quantity: system,
      counted_quantity: 5,
    });
    const records = [
      cable("a", 12),
      cable("b", 20),
      cable("c", 0),
      { ...lines[0], counted_quantity: 1 },
    ] as unknown as StockTakeItem[];
    const { result } = renderHook(
      () => useCompleteStockTakeFlow("1", records, confirm, 0),
      { wrapper },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    await waitFor(() => expect(asked.length).toBe(1));
    expect(asked[0].message).toContain("the stock of 2 products");
  });
  // Inside the tolerance a difference posts itself. Outside it, two things
  // have to be true before the stock moves: somebody has said what happened,
  // and somebody who may accept that has accepted it.
  describe("a difference beyond the tolerance", () => {
    const signIn = (permissions: string[], role = "user") =>
      useAuthStore.setState({
        user: {
          id: "1",
          full_name: "Test User",
          email: "test@example.com",
          preferred_language: "en",
          role,
          organization_id: "org-1",
          permissions,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        } as never,
      });

    const refuseOnce = (detail: Record<string, unknown>) => {
      const bodies: Record<string, unknown>[] = [];
      server.use(
        http.post("/api/v1/stock-takes/1/complete", async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          bodies.push(body);
          if (bodies.length === 1) {
            return HttpResponse.json({ detail }, { status: 409 });
          }
          return HttpResponse.json({});
        }),
      );
      return bodies;
    };

    const overTolerance = {
      code: "STOCK_TAKE_OVER_TOLERANCE",
      message: "beyond the tolerance",
      over_tolerance_items: [
        { item_name: "Bulk Goods", counted_quantity: 60, system_quantity: 100 },
      ],
    };

    it("asks somebody who may accept it, then posts", async () => {
      signIn(["stock_takes:approve"], "manager");
      const bodies = refuseOnce(overTolerance);
      confirm.mockImplementation(async (options: { message?: string }) => {
        asked.push(options);
        return true;
      });

      const { result } = renderHook(
        () => useCompleteStockTakeFlow("1", lines, confirm, 0),
        { wrapper },
      );
      await act(async () => {
        await result.current.handleComplete();
      });

      await waitFor(() => expect(bodies).toHaveLength(2));
      expect(bodies[0].force_over_tolerance).toBe(false);
      expect(bodies[1].force_over_tolerance).toBe(true);
      // The completion question and the tolerance question, in that order.
      expect(asked).toHaveLength(2);
      expect(asked[1].message).toContain("Bulk Goods");
    });

    // Two rows reading "counted 2.15, system 7.8" say nothing about what is
    // being weighed or counted, in the one dialog where somebody accepts a
    // loss on stock. The card behind it names the unit; this did not.
    it("names the unit beside each number, the way the card does", async () => {
      signIn(["stock_takes:approve"], "manager");
      refuseOnce({
        code: "STOCK_TAKE_OVER_TOLERANCE",
        message: "beyond the tolerance",
        over_tolerance_items: [
          {
            item_id: "item-1",
            item_name: "Milk",
            counted_quantity: 2.15,
            system_quantity: 7.8,
          },
        ],
      });

      const weighed = [
        { ...lines[0], uom_symbol: "pcs" },
      ] as unknown as StockTakeItem[];
      const { result } = renderHook(
        () => useCompleteStockTakeFlow("1", weighed, confirm, 0),
        { wrapper },
      );
      await act(async () => {
        await result.current.handleComplete();
      });

      await waitFor(() => expect(asked).toHaveLength(2));
      expect(asked[1].message).toContain("2.15 pcs.");
      expect(asked[1].message).toContain("7.8 pcs.");
    });

    // The card behind the dialog read "2,15 kg" while this said "2.15 kg", and
    // every abbreviated unit left a doubled full stop at the end of the
    // sentence ("…2 pcs.."): the unit's dot, then the message's own.
    it("writes the figures in the reader's language with one closing full stop", async () => {
      signIn(["stock_takes:approve"], "manager");
      refuseOnce({
        code: "STOCK_TAKE_OVER_TOLERANCE",
        message: "beyond the tolerance",
        over_tolerance_items: [
          {
            item_id: "item-1",
            item_name: "Milk",
            counted_quantity: 2.15,
            system_quantity: 7.8,
          },
        ],
      });

      const weighed = [
        { ...lines[0], uom_symbol: "pcs" },
      ] as unknown as StockTakeItem[];
      await withLanguage("pl", async () => {
        const { result } = renderHook(
          () => useCompleteStockTakeFlow("1", weighed, confirm, 0),
          { wrapper },
        );
        await act(async () => {
          await result.current.handleComplete();
        });

        await waitFor(() => expect(asked).toHaveLength(2));
      });
      const message = asked[1].message ?? "";
      expect(message).toContain("2,15 szt");
      expect(message).toContain("7,8 szt");
      expect(message).not.toContain("2.15");
      expect(message).not.toMatch(/\.\./);
    });

    it("keeps one closing full stop in English too", async () => {
      signIn(["stock_takes:approve"], "manager");
      refuseOnce({
        code: "STOCK_TAKE_OVER_CAP",
        message: "beyond the cap",
        over_cap_items: [
          {
            item_id: "item-1",
            item_name: "Milk",
            counted_quantity: 12,
            system_quantity: 2,
          },
        ],
      });

      const counted = [
        { ...lines[0], uom_symbol: "pcs" },
      ] as unknown as StockTakeItem[];
      const { result } = renderHook(
        () => useCompleteStockTakeFlow("1", counted, confirm, 0),
        { wrapper },
      );
      await act(async () => {
        await result.current.handleComplete();
      });

      await waitFor(() => expect(asked).toHaveLength(2));
      expect(asked[1].message).toContain("system 2 pcs.");
      expect(asked[1].message).not.toMatch(/\.\./);
    });

    // "3 counted quantity(ies)" is a printout, not a sentence, and this is
    // the dialog where somebody decides whether to accept a loss on stock.
    it("counts the rows in words rather than with a bracketed plural", async () => {
      signIn(["stock_takes:approve"], "manager");
      refuseOnce({
        code: "STOCK_TAKE_OVER_TOLERANCE",
        message: "beyond the tolerance",
        over_tolerance_items: [
          {
            item_name: "Bulk Goods",
            counted_quantity: 60,
            system_quantity: 100,
          },
        ],
      });
      confirm.mockImplementation(async (options: { message?: string }) => {
        asked.push(options);
        return true;
      });

      const { result } = renderHook(
        () => useCompleteStockTakeFlow("1", lines, confirm, 0),
        { wrapper },
      );
      await act(async () => {
        await result.current.handleComplete();
      });

      await waitFor(() => expect(asked).toHaveLength(2));
      expect(asked[1].message).not.toContain("(ies)");
      expect(asked[1].message).toContain("One counted quantity");
    });

    it("does not offer the button to somebody who may not press it", async () => {
      signIn([], "user");
      const bodies = refuseOnce(overTolerance);
      confirm.mockImplementation(async (options: { message?: string }) => {
        asked.push(options);
        return true;
      });

      const { result } = renderHook(
        () => useCompleteStockTakeFlow("1", lines, confirm, 0),
        { wrapper },
      );
      await act(async () => {
        await result.current.handleComplete();
      });

      // Not the server's refusal repeated back — the message says whose
      // decision this is. Without that distinction the screen offers a
      // dialog that can only ever answer 403.
      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "Accepting a difference beyond the tolerance is not yours to do — ask someone who may approve stock takes.",
        ),
      );
      // Only the completion question was asked; nothing was posted twice.
      expect(bodies).toHaveLength(1);
      expect(asked).toHaveLength(1);
    });

    // A count far above the system stock is the same decision as a
    // difference beyond the tolerance, and the server guards both with
    // `stock_takes:approve`. The over-cap branch asked its question without
    // checking, so the override it offered could only answer 403.
    const overCap = {
      code: "STOCK_TAKE_OVER_CAP",
      message: "beyond the cap",
      over_cap_items: [
        { item_name: "Flour", counted_quantity: 500, system_quantity: 10 },
      ],
    };

    it("asks before accepting a count far above the system stock", async () => {
      signIn(["stock_takes:approve"], "manager");
      const bodies = refuseOnce(overCap);
      confirm.mockImplementation(async (options: { message?: string }) => {
        asked.push(options);
        return true;
      });

      const { result } = renderHook(
        () => useCompleteStockTakeFlow("1", lines, confirm, 0),
        { wrapper },
      );
      await act(async () => {
        await result.current.handleComplete();
      });

      await waitFor(() => expect(bodies).toHaveLength(2));
      expect(bodies[0].force_over_cap).toBe(false);
      expect(bodies[1].force_over_cap).toBe(true);
      expect(asked).toHaveLength(2);
      expect(asked[1].message).toContain("Flour");
    });

    it("does not offer the over-cap override to somebody who may not approve", async () => {
      signIn([], "user");
      const bodies = refuseOnce(overCap);
      confirm.mockImplementation(async (options: { message?: string }) => {
        asked.push(options);
        return true;
      });

      const { result } = renderHook(
        () => useCompleteStockTakeFlow("1", lines, confirm, 0),
        { wrapper },
      );
      await act(async () => {
        await result.current.handleComplete();
      });

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "Accepting a count far above the system stock is not yours to do — ask someone who may approve stock takes.",
        ),
      );
      expect(bodies).toHaveLength(1);
      expect(asked).toHaveLength(1);
    });

    // A control: a difference nobody has explained cannot be accepted by
    // anybody, so no dialog offers to override it.
    it("cannot be overridden while a row still says nothing", async () => {
      signIn(["stock_takes:approve"], "manager");
      const bodies = refuseOnce({
        code: "STOCK_TAKE_TOLERANCE_REASON_MISSING",
        message: "no reason given",
        unexplained_items: [{ item_name: "Bulk Goods" }],
      });
      confirm.mockImplementation(async (options: { message?: string }) => {
        asked.push(options);
        return true;
      });

      const { result } = renderHook(
        () => useCompleteStockTakeFlow("1", lines, confirm, 0),
        { wrapper },
      );
      await act(async () => {
        await result.current.handleComplete();
      });

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "One counted quantity differs by more than the tolerance and does not say why. Give it a reason, then finish the count.",
        ),
      );
      expect(bodies).toHaveLength(1);
      expect(asked).toHaveLength(1);
    });
  });
});

describe("useCompleteStockTakeFlow — a failure that is not a question", () => {
  it("tells the counter what the server said and goes nowhere", async () => {
    // Anything that is neither a missing reason nor a difference to accept
    // has no dialog to offer; swallowing it would leave the counter on a
    // Complete button that does nothing.
    vi.mocked(toast.error).mockClear();
    server.use(
      http.post("/api/v1/stock-takes/1/complete", () =>
        HttpResponse.json(
          { detail: "This stock take is already closed" },
          { status: 409 },
        ),
      ),
    );
    const agree = vi.fn(async () => true);
    const { result } = renderHook(
      () => useCompleteStockTakeFlow("1", lines, agree, 0),
      { wrapper },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "This stock take is already closed",
      ),
    );
    expect(agree).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).not.toContain("/report");
  });

  it("falls back to its own sentence when the server gave none", async () => {
    vi.mocked(toast.error).mockClear();
    server.use(
      http.post(
        "/api/v1/stock-takes/1/complete",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const { result } = renderHook(
      () =>
        useCompleteStockTakeFlow(
          "1",
          lines,
          vi.fn(async () => true),
          0,
        ),
      { wrapper },
    );

    await act(async () => {
      await result.current.handleComplete();
    });

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalledWith(expect.any(String));
  });
});
