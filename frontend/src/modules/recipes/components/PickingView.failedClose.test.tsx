import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import PickingView from "./PickingView";
import { QueryWrapper } from "@/test/queryWrapper";
import { server } from "@/test/mocks/server";

/**
 * The real hook against a server that refuses to close the session. The view
 * used to toast "complete" or "cancelled", clear the error and close on top of
 * a session that was still open — and the meal plan opened its rating prompt
 * for it.
 */

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const start = {
  picking_session_id: "sess-1",
  recipe_name: "Pasta",
  servings: 2,
  items_to_pick: [
    {
      ingredient_id: "ing-1",
      name: "Spaghetti",
      quantity_to_pick: 200,
      uom_symbol: "g",
      recommended_item_id: "item-1",
      location: "Pantry",
      fefo_days_left: null,
      fefo_expiry_date: null,
      status: "pending" as const,
      is_linked: true,
    },
  ],
};

const busy = () =>
  HttpResponse.json({ detail: "Session is already closed" }, { status: 409 });

async function openTheSheet(onClose: () => void) {
  const user = userEvent.setup();
  render(
    <QueryWrapper>
      <PickingView recipeId="r1" recipeName="Pasta" onClose={onClose} />
    </QueryWrapper>,
  );
  await user.click(
    screen.getByRole("button", { name: /take from stock|pobierz ze stanu/i }),
  );
  await screen.findByRole("button", {
    name: /cancel picking|anuluj pobieranie/i,
  });
  return user;
}

describe("PickingView — a refused close keeps the sheet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.post("/api/v1/recipes/:id/picking/start", () =>
        HttpResponse.json(start),
      ),
    );
  });

  it("does not say complete, close or hand over a session id when completing is refused", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/complete", busy),
    );
    const onClose = vi.fn();
    const user = await openTheSheet(onClose);

    await user.click(
      screen.getAllByRole("button", {
        name: /zakończ pobieranie|finish picking/i,
      })[0],
    );
    const dialog = screen.getByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", {
        name: /zakończ pobieranie|finish picking/i,
      }),
    );

    expect(
      await screen.findByText(/Session is already closed/),
    ).toBeInTheDocument();
    expect(toast.success).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    // Still the open session: the reader can try again from here.
    expect(
      screen.getByRole("button", { name: /cancel picking|anuluj pobieranie/i }),
    ).toBeInTheDocument();
  });

  it("does not say cancelled or close when cancelling is refused", async () => {
    server.use(http.delete("/api/v1/recipes/:id/picking/:sessionId", busy));
    const onClose = vi.fn();
    const user = await openTheSheet(onClose);

    await user.click(
      screen.getByRole("button", { name: /cancel picking|anuluj pobieranie/i }),
    );

    expect(
      await screen.findByText(/Session is already closed/),
    ).toBeInTheDocument();
    expect(toast).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes as completed, with the session id, once the server accepts it", async () => {
    server.use(
      http.post("/api/v1/recipes/:id/picking/:sessionId/complete", () =>
        HttpResponse.json({ status: "completed", session_id: "sess-1" }),
      ),
    );
    const onClose = vi.fn();
    const user = await openTheSheet(onClose);

    await user.click(
      screen.getAllByRole("button", {
        name: /zakończ pobieranie|finish picking/i,
      })[0],
    );
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: /zakończ pobieranie|finish picking/i,
      }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalledWith(true, "sess-1"));
    expect(toast.success).toHaveBeenCalledOnce();
  });
});
