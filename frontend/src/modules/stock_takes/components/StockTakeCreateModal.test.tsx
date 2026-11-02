import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import StockTakeCreateModal from "./StockTakeCreateModal";
import { server } from "@/test/mocks/server";
import { render } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { serveLocations } from "@/test/serveLocations";

/**
 * A required select the reader cannot meet is not a form. When the storages
 * request failed, `storages` stayed undefined, the "you have no storages"
 * branch never opened, and the modal rendered whole with an empty required
 * select — the same shape the quick-add form once had.
 */
describe("StockTakeCreateModal", () => {
  it("does not ask for a description or notes that cannot be read afterwards", () => {
    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    expect(screen.queryByLabelText("Description")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Notes")).not.toBeInTheDocument();
  });

  it("creates a stock take without sending unused description and notes fields", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const submitted = vi.fn();
    serveLocations([
      { id: "s-1", name: "Fridge" },
      { id: "s-2", name: "Freezer" },
    ]);
    server.use(
      http.post("/api/v1/stock-takes", async ({ request }) => {
        submitted(await request.json());
        return HttpResponse.json({ id: "new-st" }, { status: 201 });
      }),
    );

    render(<StockTakeCreateModal isOpen onClose={onClose} />);

    await user.click(await screen.findByRole("combobox", { name: /Location/ }));
    await user.click(await screen.findByText("Fridge"));
    await user.type(
      screen.getByRole("textbox", { name: "Stock take name" }),
      "Monthly check",
    );
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(submitted).toHaveBeenCalledExactlyOnceWith({
      location_id: "s-1",
      name: "Monthly check",
      blind_mode: false,
      require_full_count: true,
    });
  });

  it("says the storages could not be read instead of rendering a select with nothing to pick", async () => {
    server.use(
      http.get(
        "/api/v1/locations",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Location")).not.toBeInTheDocument();
  });

  it("still offers to create the missing storage when the read succeeded empty", async () => {
    // An honest empty — the storages were read and there are none — keeps
    // the quick-add form's answer: create the first one in place, no select at all.
    serveLocations([]);

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    expect(await screen.findByText("No locations yet")).toBeInTheDocument();
    expect(screen.queryByLabelText("Location")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

/**
 * A stock take counts what stock flows may offer: a place a module owns is
 * never where warehouse stock stands, so it stays out of the picker whatever
 * the module-data policy mixes into the general lists — and the empty picker
 * gives the advice that works under that same purpose.
 */
describe("StockTakeCreateModal — which locations the picker offers", () => {
  const internal = { id: "loc-1", name: "Main Warehouse", context_tag: null };
  const moduleRack = {
    id: "loc-rack",
    name: "Server Rack A",
    context_tag: "equipment",
  };

  function serveStorages(
    showModuleData: boolean,
    rows = [internal, moduleRack],
  ) {
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "org-1",
          name: "Test Org",
          currency: "PLN",
          settings: showModuleData ? { show_module_data: true } : {},
        }),
      ),
    );
    return serveLocations(rows);
  }

  // Every other field in this modal hands its label to the shared component,
  // which binds the two. The tolerance field had a bare <label> beside an
  // <Input> with no id, so `input.labels` was empty — one field, in one
  // window, from one release.
  it("binds the tolerance label to the field it names", async () => {
    serveLocations([{ id: "s-1", name: "Fridge" }]);

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    const tolerance = await screen.findByLabelText(/tolerance/i);
    expect(tolerance).toHaveAttribute("id");
    expect((tolerance as HTMLInputElement).labels).toHaveLength(1);
  });

  it("keeps module-owned locations out by default", async () => {
    serveStorages(false, [
      internal,
      { ...moduleRack },
      { id: "l2", name: "Second shelf", context_tag: null },
    ]);

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("combobox", { name: /Location/ }));
    expect(await screen.findByText("Main Warehouse")).toBeInTheDocument();
    expect(screen.queryByText(/Server Rack/)).not.toBeInTheDocument();
  });

  it("keeps them out even when the organization mixes module data into lists", async () => {
    const requests = serveStorages(true, [
      internal,
      moduleRack,
      { id: "l2", name: "Second shelf", context_tag: null },
    ]);

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("combobox", { name: /Location/ }));
    expect(await screen.findByText("Main Warehouse")).toBeInTheDocument();
    expect(screen.queryByText(/Server Rack/)).not.toBeInTheDocument();
    expect(
      requests.every((r) => r.get("exclude_module_contexts") === "true"),
    ).toBe(true);
  });

  it("selects the only location it may offer instead of asking which one", async () => {
    serveStorages(false);

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: /Location/ }),
      ).toHaveTextContent("Main Warehouse"),
    );
  });

  it("never reads the whole list of locations to fill the picker", async () => {
    const requests = serveLocations(
      Array.from({ length: 1500 }, (_, i) => ({
        id: `s${i}`,
        name: `Bin ${i}`,
      })),
    );

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("combobox", { name: /Location/ }));
    await screen.findByText("Bin 0");
    expect(requests.every((r) => Number(r.get("limit")) <= 30)).toBe(true);
  });

  it("tells the reader to add a location where the picker excludes module places", async () => {
    // Every place the organization keeps belongs to a module: the stock
    // picker has nothing to offer, and the settings switch reveals nothing
    // in it — the advice is the one that works, create a location.
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "org-1",
          name: "Test Org",
          currency: "PLN",
          settings: {},
        }),
      ),
    );
    serveLocations([moduleRack]);

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    expect(await screen.findByText("No locations yet")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /open settings/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Location")).not.toBeInTheDocument();
  });
});

/**
 * The options on the form are closures over its draft; each has to reach the
 * request, or the counter gets a count they did not ask for.
 */
describe("StockTakeCreateModal — what the options send", () => {
  it("sends blind mode, the full-count switch and the tolerance as set", async () => {
    const user = userEvent.setup();
    const submitted = vi.fn();
    serveLocations([{ id: "s-1", name: "Fridge" }]);
    server.use(
      http.post("/api/v1/stock-takes", async ({ request }) => {
        submitted(await request.json());
        return HttpResponse.json({ id: "new-st" }, { status: 201 });
      }),
    );

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: /Location/ }),
      ).toHaveTextContent("Fridge"),
    );

    await user.type(
      screen.getByRole("textbox", { name: "Stock take name" }),
      "Spot check",
    );
    await user.click(screen.getByRole("checkbox", { name: /Blind mode/ }));
    await user.click(
      screen.getByRole("checkbox", { name: /Require full count/ }),
    );
    await user.type(screen.getByLabelText(/Tolerance/), "2.5");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(submitted).toHaveBeenCalledOnce());
    expect(submitted).toHaveBeenCalledWith({
      location_id: "s-1",
      name: "Spot check",
      blind_mode: true,
      require_full_count: false,
      tolerance_percent: 2.5,
    });
  });

  it("drops the tolerance from the request when the field is emptied again", async () => {
    const user = userEvent.setup();
    const submitted = vi.fn();
    serveLocations([{ id: "s-1", name: "Fridge" }]);
    server.use(
      http.post("/api/v1/stock-takes", async ({ request }) => {
        submitted(await request.json());
        return HttpResponse.json({ id: "new-st" }, { status: 201 });
      }),
    );

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: /Location/ }),
      ).toHaveTextContent("Fridge"),
    );

    await user.type(
      screen.getByRole("textbox", { name: "Stock take name" }),
      "Spot check",
    );
    const tolerance = screen.getByLabelText(/Tolerance/);
    await user.type(tolerance, "4");
    await user.clear(tolerance);
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(submitted).toHaveBeenCalledOnce());
    expect(submitted.mock.calls[0][0]).not.toHaveProperty("tolerance_percent");
  });

  it("says why the count could not be created and keeps the form open", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    serveLocations([{ id: "s-1", name: "Fridge" }]);
    server.use(
      http.post("/api/v1/stock-takes", () =>
        HttpResponse.json(
          { detail: "This location is already being counted" },
          { status: 409 },
        ),
      ),
    );

    render(<StockTakeCreateModal isOpen onClose={onClose} />);
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: /Location/ }),
      ).toHaveTextContent("Fridge"),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Stock take name" }),
      "Spot check",
    );
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText("This location is already being counted"),
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("asks for the locations again when the reader presses Try again", async () => {
    const user = userEvent.setup();
    let failing = true;
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        if (failing) return new HttpResponse(null, { status: 500 });
        return HttpResponse.json({
          items: [{ id: "s-1", name: "Fridge", parent_id: null }],
          total: 1,
          limit: Number(new URL(request.url).searchParams.get("limit") ?? 30),
          offset: 0,
          has_more: false,
        });
      }),
    );

    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);
    const retry = await screen.findByRole("button", { name: /try again/i });
    failing = false;
    await user.click(retry);

    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: /Location/ }),
      ).toHaveTextContent("Fridge"),
    );
  });
});

describe("StockTakeCreateModal — a count without a name", () => {
  it("sends nothing without a name, and says what is missing", async () => {
    const user = userEvent.setup();
    const submitted = vi.fn();
    serveLocations([
      { id: "s-1", name: "Fridge" },
      { id: "s-2", name: "Freezer" },
    ]);
    server.use(
      http.post("/api/v1/stock-takes", () => {
        submitted();
        return HttpResponse.json({ id: "x" }, { status: 201 });
      }),
    );
    render(<StockTakeCreateModal isOpen onClose={vi.fn()} />);

    await user.click(await screen.findByRole("combobox", { name: /Location/ }));
    await user.click(await screen.findByText("Fridge"));
    // The browser's own check stops an empty required field first; the
    // form's guard is what holds where that check does not run.
    fireEvent.submit(document.getElementById("stock-take-create-form")!);
    expect(await screen.findByText("Name is required")).toBeInTheDocument();
    expect(submitted).not.toHaveBeenCalled();
  });
});
