import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { NewLocationSheet } from "./NewLocationSheet";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const shelf = { id: "loc-1", name: "Main Storage", parent_id: null };

/**
 * A storage list that grows when a location is created, and a record of how
 * many times it was read since — the pick must not arrive before the list
 * that offers it.
 */
function mockServer() {
  const state = {
    rows: [shelf] as Array<Record<string, unknown>>,
    posted: [] as Array<Record<string, unknown>>,
    readsAfterCreate: 0,
  };
  server.use(
    http.get("/api/v1/organizations/my", () =>
      HttpResponse.json({ id: "org-1", name: "Org", settings: {} }),
    ),
    http.get("/api/v1/locations", () => {
      if (state.posted.length > 0) state.readsAfterCreate += 1;
      return HttpResponse.json(onePage(state.rows));
    }),
    http.post("/api/v1/locations", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      state.posted.push(body);
      const created = { id: "loc-2", ...body };
      state.rows = [...state.rows, created];
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  return state;
}

function renderSheet(props: Partial<Parameters<typeof NewLocationSheet>[0]>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NewLocationSheet open onClose={vi.fn()} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NewLocationSheet", () => {
  it("creates the location inside the place chosen for it", async () => {
    const state = mockServer();
    const onCreated = vi.fn();
    renderSheet({ onCreated });

    await userEvent.type(screen.getByLabelText(/^name$/i), "Rack B");
    await userEvent.click(
      await screen.findByRole("combobox", { name: /inside/i }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /main storage/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(state.posted).toEqual([{ name: "Rack B", parent_id: "loc-1" }]);
    expect(onCreated).toHaveBeenCalledWith(
      expect.objectContaining({ id: "loc-2" }),
    );
  });

  it("hands the new location over only once the list holds it", async () => {
    // The product form drops a chosen location its picker does not offer.
    // Picked before the storage list was read again, the new location was
    // emptied out of the field it had just been put into.
    const state = mockServer();
    let readsWhenPicked = -1;
    const onCreated = vi.fn(() => {
      readsWhenPicked = state.readsAfterCreate;
    });
    renderSheet({ onCreated });

    await userEvent.type(screen.getByLabelText(/^name$/i), "Back Room");
    await userEvent.keyboard("{Enter}");

    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(readsWhenPicked).toBeGreaterThan(0);
  });

  it("starts from what the reader searched for", () => {
    mockServer();
    renderSheet({ initialName: "Cold room" });

    expect(screen.getByLabelText(/^name$/i)).toHaveValue("Cold room");
  });

  // Opened from an empty picker, the sheet renders inside the product form;
  // none of its buttons may submit that form.
  it("submits no form it is rendered inside", async () => {
    mockServer();
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <form onSubmit={onSubmit}>
            <NewLocationSheet open onClose={vi.fn()} />
          </form>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    for (const button of await screen.findAllByRole("button")) {
      if (!(button as HTMLButtonElement).disabled) {
        await userEvent.click(button);
      }
    }
    await userEvent.type(screen.getByLabelText(/^name$/i), "Rack B");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("saves nothing without a name", () => {
    mockServer();
    renderSheet({});

    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });
});
