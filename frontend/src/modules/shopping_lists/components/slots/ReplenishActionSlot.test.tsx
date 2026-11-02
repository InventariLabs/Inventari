/**
 * The dashboard's replenish door, as the shopping lists draw it.
 *
 * It reads the engine's own answer — the one the modal behind it shows — and
 * is a write: the modal's only answer puts rows on a list.
 */
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import ReplenishActionSlot from "./ReplenishActionSlot";

const canWrite = vi.hoisted(() => ({ value: true }));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => canWrite.value,
}));

const peas = {
  item_id: "peas",
  name: "Frozen peas",
  quantity: 1,
  priority: 0,
  source: "low_stock",
};

function serve(suggestions: object[]) {
  server.use(
    http.get("*/shopping-lists/suggestions", () =>
      HttpResponse.json({ suggestions }),
    ),
  );
}

function renderDoor(onOpen = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ReplenishActionSlot data={{ onOpen }} />
    </QueryClientProvider>,
  );
  return onOpen;
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });
}

describe("the replenish door", () => {
  beforeEach(() => {
    canWrite.value = true;
  });

  it("opens the modal when the engine proposes something", async () => {
    serve([peas]);
    const onOpen = renderDoor();

    await userEvent.click(
      await screen.findByRole("button", { name: /replenish all/i }),
    );
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("stays shut for an account that cannot write the list", async () => {
    // The door is the write: it opens a modal whose only answer, "Add
    // selected", writes shopping-list rows the account may only read.
    canWrite.value = false;
    serve([peas]);
    renderDoor();

    await settle();
    expect(
      screen.queryByRole("button", { name: /replenish all/i }),
    ).not.toBeInTheDocument();
  });

  it("stays shut when the engine proposes nothing", async () => {
    // The door reads the engine's own answer, not the tile counting
    // shortages: an item can be below its threshold and still be filtered
    // out of the proposals — already on a list, stock in transit, outside an
    // internal location — and expired goods are thrown out, not reordered.
    // Gated on the shortage row instead, the button stood open over an empty
    // modal; the measured path was "Replenish All, add, come back".
    serve([]);
    renderDoor();

    await settle();
    expect(
      screen.queryByRole("button", { name: /replenish all/i }),
    ).not.toBeInTheDocument();
  });

  it("names the purchasing policy wherever the door stays shut", async () => {
    // A hidden button with no words is a silence: say which products the
    // proposals leave out on purpose.
    serve([]);
    renderDoor();
    expect(
      await screen.findByText(/stock in use elsewhere/i),
    ).toBeInTheDocument();
  });

  it("names the policy to an account that cannot write, too", async () => {
    canWrite.value = false;
    serve([peas]);
    renderDoor();
    expect(
      await screen.findByText(/stock in use elsewhere/i),
    ).toBeInTheDocument();
  });

  it("says nothing of the policy while the door is open", async () => {
    serve([peas]);
    renderDoor();
    await screen.findByRole("button", { name: /replenish all/i });
    expect(
      screen.queryByText(/stock in use elsewhere/i),
    ).not.toBeInTheDocument();
  });
});
