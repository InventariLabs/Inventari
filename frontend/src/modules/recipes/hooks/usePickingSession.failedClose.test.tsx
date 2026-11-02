import type { ReactNode } from "react";
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import { http, HttpResponse } from "msw";
import { usePickingSession } from "./usePickingSession";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/**
 * Closing a session is the backend's business. When the backend refuses, the
 * session is still open — the hook said "complete" and "cancelled" anyway, the
 * view reported success on top of it, and the reader lost the sheet they could
 * have retried from.
 */

const start = {
  picking_session_id: "session-abc",
  recipe_name: "Pasta",
  servings: 2,
  items_to_pick: [
    {
      ingredient_id: "ing-1",
      name: "Spaghetti",
      quantity_to_pick: 200,
      uom_symbol: "g",
      recommended_item_id: null,
      location: "Pantry",
      fefo_days_left: null,
      fefo_expiry_date: null,
      status: "pending" as const,
    },
  ],
};

const lastPick = {
  status: "picked",
  ingredient_id: "ing-1",
  ingredient_name: "Spaghetti",
  quantity_consumed: 200,
  uom_symbol: "g",
  session_complete: true,
  message: "picked",
};

const refuse = (path: string, method: "post" | "delete") =>
  http[method](`/api/v1/recipes/:id/picking/:sessionId${path}`, () =>
    HttpResponse.json({ detail: "Session is already closed" }, { status: 409 }),
  );

async function openSession() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => usePickingSession("recipe-1"), { wrapper });
  await act(async () => {
    await hook.result.current.startSession(2);
  });
  return hook;
}

describe("usePickingSession — a refused close is not a close", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json(start),
      ),
    );
  });

  it("keeps the session open and says so when completing is refused", async () => {
    server.use(refuse("/complete", "post"));
    const { result } = await openSession();

    let done: boolean | undefined;
    await act(async () => {
      done = await result.current.completeSession();
    });

    expect(done).toBe(false);
    expect(result.current.state.phase).toBe("active");
    expect(result.current.error).toContain("Session is already closed");
  });

  it("answers true when completing went through", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/complete", () =>
        HttpResponse.json({ status: "completed", session_id: "session-abc" }),
      ),
    );
    const { result } = await openSession();

    let done: boolean | undefined;
    await act(async () => {
      done = await result.current.completeSession();
    });

    expect(done).toBe(true);
    expect(result.current.state.phase).toBe("complete");
  });

  it("keeps the session open and says so when cancelling is refused", async () => {
    server.use(refuse("", "delete"));
    const { result } = await openSession();

    let done: boolean | undefined;
    await act(async () => {
      done = await result.current.cancelSession();
    });

    expect(done).toBe(false);
    expect(result.current.state.phase).toBe("active");
    expect(result.current.error).toContain("Session is already closed");
  });

  it("answers true when cancelling went through", async () => {
    server.use(
      http.delete(
        "/api/v1/recipes/:id/picking/:sessionId",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const { result } = await openSession();

    let done: boolean | undefined;
    await act(async () => {
      done = await result.current.cancelSession();
    });

    expect(done).toBe(true);
    expect(result.current.state.phase).toBe("cancelled");
  });

  it("does not report the session done when the last pick could not close it", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json(lastPick),
      ),
      refuse("/complete", "post"),
    );
    const { result } = await openSession();

    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });

    // The ingredient did leave the shelf, so the row is ticked — but the
    // session is still open and the reader can finish it from the sheet.
    expect(result.current.state.phase).toBe("active");
    if (result.current.state.phase === "active") {
      expect(result.current.state.items[0].status).toBe("picked");
    }
    expect(result.current.error).toContain("Session is already closed");
  });

  it("does not report the session done when a chosen candidate could not close it", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json({
          status: "disambiguation_required",
          ingredient_id: "ing-1",
          candidates: [],
          message: "choose",
        }),
      ),
      refuse("/complete", "post"),
    );
    const { result } = await openSession();
    await act(async () => {
      await result.current.scan({ barcode: "123" });
    });
    expect(result.current.state.phase).toBe("disambiguation");

    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json(lastPick),
      ),
    );
    await act(async () => {
      await result.current.resolveDisambiguation("item-1");
    });

    expect(result.current.state.phase).toBe("active");
    if (result.current.state.phase === "active") {
      expect(result.current.state.items[0].status).toBe("picked");
    }
    expect(result.current.error).toContain("Session is already closed");
  });

  it("keeps the suggestion open when dismissing it could not close the session", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/scan", () =>
        HttpResponse.json({
          ...lastPick,
          opened_suggestion: {
            item_id: "item-9",
            name: "Open pack",
            quantity: 50,
            uom_symbol: "g",
          },
        }),
      ),
      refuse("/complete", "post"),
    );
    const { result } = await openSession();

    await act(async () => {
      await result.current.scan({ item_id: "item-1" });
    });
    expect(result.current.state.phase).toBe("opened_suggestion");

    await act(async () => {
      await result.current.dismissOpenedSuggestion();
    });

    expect(result.current.state.phase).toBe("opened_suggestion");
    expect(result.current.error).toContain("Session is already closed");
  });
});

/**
 * A 5xx carries no sentence for the reader (its detail is for the logs), so
 * what the banner shows is the hook's own fallback — and that has to be in
 * the reader's language, not the English the hook was written in.
 */
describe("usePickingSession — a failing server is reported in the reader's language", () => {
  const failing = (path: string, method: "post" | "delete") =>
    http[method](`/api/v1/recipes/:id/picking/:sessionId${path}`, () =>
      HttpResponse.json({ detail: "Traceback …" }, { status: 500 }),
    );

  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json(start),
      ),
    );
  });

  it("when finishing fails", async () => {
    server.use(failing("/complete", "post"));
    await withLanguage("pl", async () => {
      const { result } = await openSession();
      await act(async () => {
        await result.current.completeSession();
      });
      expect(result.current.error).toBe(
        "Nie udało się zakończyć pobierania. Spróbuj ponownie.",
      );
    });
  });

  it("when cancelling fails", async () => {
    server.use(failing("", "delete"));
    await withLanguage("pl", async () => {
      const { result } = await openSession();
      await act(async () => {
        await result.current.cancelSession();
      });
      expect(result.current.error).toBe(
        "Nie udało się anulować pobierania. Spróbuj ponownie.",
      );
    });
  });

  it("when starting fails", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json({ detail: "Traceback …" }, { status: 500 }),
      ),
    );
    await withLanguage("pl", async () => {
      const { result } = await openSession();
      expect(result.current.error).toBe(
        "Nie udało się rozpocząć pobierania. Spróbuj ponownie.",
      );
    });
  });
});
