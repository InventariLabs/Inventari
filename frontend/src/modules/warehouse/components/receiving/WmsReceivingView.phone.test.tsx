import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { act, render, screen, waitFor, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { server } from "@/test/mocks/server";
import { toast } from "sonner";
import { serveLocations } from "@/test/serveLocations";
import { scanIntoField } from "@/test/scanner";
import WmsReceivingView from "./WmsReceivingView";
import type {
  WmsReceiveLine,
  WmsReceiveSession,
} from "@/modules/warehouse/api/documents_receiving";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

// The camera is a live device; the screen is what these tests read.
vi.mock("@/hooks/useScanCamera", () => ({
  useScanCamera: () => ({
    scannerError: null,
    isCameraActive: false,
    isCameraRunning: false,
    setIsCameraActive: vi.fn(),
    restartCamera: vi.fn(),
    startCamera: vi.fn(),
    resumeCamera: vi.fn(),
    pauseCamera: vi.fn(),
    toggleTorch: vi.fn(),
    isTorchOn: false,
  }),
}));

const DOC = "doc-1";
const BASE = `/api/v1/warehouse/documents/${DOC}/receiving`;

beforeEach(() => {
  // A phone: the session is worked one item at a time.
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(max-width: 639px)",
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
});

function line(
  id: string,
  name: string,
  overrides: Partial<WmsReceiveLine> = {},
): WmsReceiveLine {
  return {
    id,
    document_line_id: `doc-${id}`,
    pick_order: 1,
    status: "pending",
    received_quantity: 0,
    product_name: name,
    lot_name: null,
    expected_quantity: 10,
    uom_symbol: "pcs",
    from_order: true,
    ...overrides,
  };
}

function session(
  lines: WmsReceiveLine[],
  status = "active",
): WmsReceiveSession {
  return {
    id: "session-1",
    document_id: DOC,
    assigned_to: null,
    status,
    started_at: "2026-10-22T08:00:00Z",
    completed_at: null,
    total_lines: lines.length,
    received_lines: 0,
    pending_lines: 0,
    shelf_scan_required: false,
    lines,
  };
}

/** A delivery opened again after the app was closed: the rice is done. */
const reopened = () =>
  session([
    line("rice", "Jasmine Rice", { status: "received", received_quantity: 40 }),
    line("plums", "Damson Plums", {
      planned_location_id: "loc-fridge",
      planned_location_name: "Fridge A",
      planned_source: "rule",
      planned_rule_match_key: "category",
      planned_rule_match_name: "Fruit",
    }),
    line("gouda", "Gouda Cheese", {
      expected_quantity: 12,
      planned_location_id: "loc-fridge-b",
      planned_location_name: "Fridge B",
      planned_source: "record",
    }),
  ]);

function serveDocument() {
  server.use(
    http.get(`/api/v1/warehouse/documents/${DOC}`, () =>
      HttpResponse.json({
        id: DOC,
        number: "PZ/2026/015",
        type: "IN",
        status: "CONFIRMED",
        partner_snapshot: { name: "Hurtownia Kowalski" },
        lines: [],
      }),
    ),
  );
}

describe("WmsReceivingView on a phone", () => {
  it("opens again on the next item, with the progress the delivery already has", async () => {
    serveDocument();
    server.use(http.post(`${BASE}/start`, () => HttpResponse.json(reopened())));

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);

    const card = await screen.findByRole("region", { name: "Damson Plums" });
    expect(within(card).getByText("Still due 10 pcs.")).toBeInTheDocument();
    // The count starts at what was ordered: confirming says all of it came.
    expect(
      within(card).getByRole("spinbutton", {
        name: "How many of Damson Plums arrived",
      }),
    ).toHaveValue(10);
    expect(within(card).getByText("Put on")).toBeInTheDocument();
    expect(within(card).getByText("Fridge A")).toBeInTheDocument();
    expect(within(card).getByText(/Fruit/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "33",
    );
    expect(screen.getAllByText("1 of 3").length).toBeGreaterThan(0);
    expect(
      await screen.findByRole("heading", {
        name: "Delivery from Hurtownia Kowalski",
      }),
    ).toBeInTheDocument();
  });

  it("keeps saying how much of a counted item went to quarantine, and why", async () => {
    // The card shows only the next open item; an item counted with part of
    // it quarantined left the screen with no trace of that part.
    serveDocument();
    server.use(
      http.post(`${BASE}/start`, () =>
        HttpResponse.json(
          session([
            line("butter", "Butter Extra 82%", {
              status: "short",
              expected_quantity: 12,
              received_quantity: 10,
              held_quantity: 2,
              discrepancy_code: "DAMAGE",
            }),
            line("plums", "Damson Plums"),
          ]),
        ),
      ),
    );

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);

    await screen.findByRole("region", { name: "Damson Plums" });
    // The received figure sits in the same entry as the quarantined part
    // and its reason, not on the next item's card.
    const entry = screen.getByText("Butter Extra 82%").closest("li");
    expect(entry).not.toBeNull();
    expect(
      within(entry as HTMLElement).getByText("10/12 pcs."),
    ).toBeInTheDocument();
    expect(
      within(entry as HTMLElement).getByText("2 pcs. in quarantine — Damage"),
    ).toBeInTheDocument();
  });

  it("records the count set with the buttons as the line's total and moves to the next item", async () => {
    serveDocument();
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(`${BASE}/start`, () => HttpResponse.json(reopened())),
      http.post(`${BASE}/session-1/short-receive`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          status: "short_receive_confirmed",
          line_id: "plums",
          product_name: "Damson Plums",
          received_quantity: 8,
          expected_quantity: 10,
          uom_symbol: "pcs",
          message: "",
          session_complete: false,
        });
      }),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    const card = await screen.findByRole("region", { name: "Damson Plums" });
    await user.click(within(card).getByRole("button", { name: "Decrease" }));
    await user.click(within(card).getByRole("button", { name: "Decrease" }));

    expect(
      within(card).getByText("2 pcs. missing. It stays expected on the order."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Correct, next" }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({
      line_id: "plums",
      received_quantity: 8,
      replace_scans: false,
    });
    expect(
      await screen.findByRole("region", { name: "Gouda Cheese" }),
    ).toBeInTheDocument();
    // The last open item finishes the delivery instead of moving on.
    expect(
      screen.getByRole("button", { name: "Correct, finish receiving" }),
    ).toBeInTheDocument();
  });

  it("records part of the count as damaged, with the reason, from the card", async () => {
    serveDocument();
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(`${BASE}/start`, () => HttpResponse.json(reopened())),
      http.post(`${BASE}/session-1/short-receive`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          status: "short_receive_confirmed",
          line_id: "plums",
          product_name: "Damson Plums",
          received_quantity: 10,
          expected_quantity: 10,
          uom_symbol: "pcs",
          message: "",
          session_complete: false,
        });
      }),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    const card = await screen.findByRole("region", { name: "Damson Plums" });
    await user.click(
      within(card).getByRole("button", {
        name: "Some of it is damaged or on hold",
      }),
    );

    // The sheet opens on the count already set on the card, not on the scans.
    const sheet = await screen.findByRole("dialog", {
      name: "Record received quantity",
    });
    expect(within(sheet).getByTestId("short-receive-qty")).toHaveValue(10);
    await user.type(within(sheet).getByTestId("short-receive-held"), "2");
    expect(within(sheet).getByRole("combobox")).toHaveDisplayValue("Damage");
    await user.click(within(sheet).getByRole("button", { name: /Confirm/ }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({
      line_id: "plums",
      received_quantity: 10,
      held_quantity: 2,
      discrepancy_code: "DAMAGE",
    });
  });

  it("does not call goods nobody ordered still due", async () => {
    // The phone's list of goods with no order hands its counts to the
    // session as the lines' expected quantities: three bolts written down
    // read as "Still due 3 pcs." on a card nobody had ordered anything for.
    serveDocument();
    server.use(
      http.post(`${BASE}/start`, () =>
        HttpResponse.json(
          session([
            line("bolt", "Hex Bolt", {
              expected_quantity: 3,
              from_order: false,
            }),
          ]),
        ),
      ),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    const card = await screen.findByRole("region", { name: "Hex Bolt" });

    expect(within(card).getByText("Expected 3 pcs.")).toBeInTheDocument();
    expect(within(card).queryByText(/Still due/)).not.toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Decrease" }));
    expect(
      within(card).getByText("1 pcs. fewer than expected."),
    ).toBeInTheDocument();
  });

  it("brings back a count typed and not confirmed after Back and resume", async () => {
    serveDocument();
    server.use(http.post(`${BASE}/start`, () => HttpResponse.json(reopened())));
    const user = userEvent.setup();

    const first = render(
      <WmsReceivingView documentId={DOC} onClose={vi.fn()} />,
    );
    let card = await screen.findByRole("region", { name: "Damson Plums" });
    await user.click(within(card).getByRole("button", { name: "Decrease" }));
    await user.click(within(card).getByRole("button", { name: "Decrease" }));
    expect(
      within(card).getByText("2 pcs. missing. It stays expected on the order."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));
    first.unmount();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    card = await screen.findByRole("region", { name: "Damson Plums" });
    expect(
      within(card).getByText("2 pcs. missing. It stays expected on the order."),
    ).toBeInTheDocument();
  });

  it("asks before a count past the tolerance lands, then sends it confirmed", async () => {
    // A worker who may receive over tolerance is asked, not refused: the
    // session names the surplus, records nothing, and takes the same count
    // again with the answer.
    serveDocument();
    const confirmations: (string | null)[] = [];
    server.use(
      http.post(`${BASE}/start`, () => HttpResponse.json(reopened())),
      http.post(`${BASE}/session-1/short-receive`, ({ request }) => {
        const confirmed = new URL(request.url).searchParams.get(
          "confirm_surplus",
        );
        confirmations.push(confirmed);
        return confirmed === "true"
          ? HttpResponse.json({
              status: "short_receive_confirmed",
              line_id: "plums",
              product_name: "Damson Plums",
              received_quantity: 12,
              expected_quantity: 10,
              uom_symbol: "pcs",
              message: "",
              session_complete: false,
            })
          : HttpResponse.json(
              {
                detail: {
                  code: "SURPLUS_NEEDS_CONFIRMATION",
                  message:
                    "Damson Plums: receiving 12 is 2 more than the 10 left on order PO/2026/002, line 2. Receive the surplus?",
                },
              },
              { status: 409 },
            );
      }),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    const card = await screen.findByRole("region", { name: "Damson Plums" });
    await user.click(within(card).getByRole("button", { name: "Increase" }));
    await user.click(within(card).getByRole("button", { name: "Increase" }));
    await user.click(screen.getByRole("button", { name: "Correct, next" }));

    const question = await screen.findByRole("alertdialog");
    expect(question).toHaveTextContent(
      "receiving 12 is 2 more than the 10 left on order PO/2026/002, line 2",
    );
    // Nothing was recorded: the card behind the question is still the one
    // in hand.
    expect(
      screen.getByRole("region", { name: "Damson Plums", hidden: true }),
    ).toBeInTheDocument();

    await user.click(
      within(question).getByRole("button", { name: "Receive the surplus" }),
    );

    expect(
      await screen.findByRole("region", { name: "Gouda Cheese" }),
    ).toBeInTheDocument();
    expect(confirmations).toEqual([null, "true"]);
  });

  it("takes a scanned product in any order", async () => {
    serveDocument();
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(`${BASE}/start`, () => HttpResponse.json(reopened())),
      http.post(`${BASE}/session-1/scan`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          status: "identified",
          line_id: "gouda",
          product_name: "Gouda Cheese",
          received_quantity: 0,
          expected_quantity: 12,
          uom_symbol: "pcs",
          message: "",
          session_complete: false,
        });
      }),
    );
    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    await screen.findByRole("region", { name: "Damson Plums" });
    scanIntoField(
      "8710000000001",
      screen.getByRole("textbox", {
        name: "Scan the next product, in any order",
      }) as HTMLInputElement,
    );

    const card = await screen.findByRole("region", { name: "Gouda Cheese" });
    // The scan only names the item; the count is the card's.
    expect(body).toMatchObject({ barcode: "8710000000001", identify: true });
    expect(within(card).getByText("Scanned")).toBeInTheDocument();
    expect(within(card).getByRole("spinbutton")).toHaveValue(12);
    // A plan no rule made still says why it chose the location.
    expect(within(card).getByText("Fridge B")).toBeInTheDocument();
    expect(
      within(card).getByText("Where the rest of it already is"),
    ).toBeInTheDocument();
  });

  it("keeps the card of a one-unit line after its scan, until the count is confirmed", async () => {
    serveDocument();
    let shortReceived = false;
    let completed = false;
    server.use(
      http.post(`${BASE}/start`, () =>
        HttpResponse.json(
          session([line("nut", "Hex Nut", { expected_quantity: 1 })]),
        ),
      ),
      // As the server answers: a scan that does not only identify counts
      // the unit, and the one-unit line closes the session.
      http.post(`${BASE}/session-1/scan`, async ({ request }) => {
        const sent = (await request.json()) as { identify?: boolean };
        return HttpResponse.json({
          status: sent.identify ? "identified" : "received",
          line_id: "nut",
          product_name: "Hex Nut",
          received_quantity: sent.identify ? 0 : 1,
          expected_quantity: 1,
          uom_symbol: "pcs",
          message: "",
          session_complete: !sent.identify,
        });
      }),
      http.post(`${BASE}/session-1/short-receive`, () => {
        shortReceived = true;
        return HttpResponse.json({
          status: "short_receive_confirmed",
          line_id: "nut",
          product_name: "Hex Nut",
          received_quantity: 1,
          expected_quantity: 1,
          uom_symbol: "pcs",
          message: "",
          session_complete: true,
        });
      }),
      http.patch(`/api/v1/warehouse/documents/${DOC}/complete`, () => {
        completed = true;
        return HttpResponse.json({
          id: DOC,
          number: "PZ/2026/015",
          type: "IN",
          status: "COMPLETED",
          reversed_by_id: null,
          lines: [],
        });
      }),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    await screen.findByRole("region", { name: "Hex Nut" });
    scanIntoField(
      "RV-NUT",
      screen.getByRole("textbox", {
        name: "Scan the next product, in any order",
      }) as HTMLInputElement,
    );

    const card = await screen.findByRole("region", { name: "Hex Nut" });
    expect(await within(card).findByText("Scanned")).toBeInTheDocument();
    expect(shortReceived).toBe(false);
    expect(completed).toBe(false);

    await user.click(
      screen.getByRole("button", { name: "Correct, finish receiving" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Received 1 line" }),
    ).toBeInTheDocument();
    expect(shortReceived).toBe(true);
  });

  it("names the shelf by its code, and offers one when the plan is the whole warehouse", async () => {
    serveDocument();
    const order: string[] = [];
    // The plans are read again after the shelf is named, and that answer
    // may arrive after the count: it is the server's view from before it.
    let counted: () => void = () => undefined;
    const countLanded = new Promise<void>((resolve) => (counted = resolve));
    serveLocations([
      { id: "wh", name: "Main Warehouse", short_code: "MAIN", is_leaf: false },
      {
        id: "shelf-a2",
        name: "Aisle A, shelf 2",
        parent_id: "wh",
        short_code: "A-02-01",
      },
    ]);
    const bolts = line("bolts", "Hex Bolt M8", {
      expected_quantity: 5,
      planned_location_id: "wh",
      planned_location_name: "Main Warehouse",
      planned_source: "document",
      suggested_location_id: "shelf-a2",
      suggested_location_name: "Aisle A, shelf 2",
      suggested_source: "stock",
    });
    server.use(
      http.post(`${BASE}/start`, () => HttpResponse.json(session([bolts]))),
      http.patch(
        `/api/v1/warehouse/documents/${DOC}/lines/doc-bolts`,
        async ({ request }) => {
          const sent = (await request.json()) as Record<string, unknown>;
          order.push(`target:${String(sent.target_location_id)}`);
          return HttpResponse.json({ id: DOC, lines: [] });
        },
      ),
      http.get(`${BASE}/session-1`, async () => {
        const stale = session([{ ...bolts, target_location_id: "shelf-a2" }]);
        await countLanded;
        await new Promise((resolve) => setTimeout(resolve, 20));
        return HttpResponse.json(stale);
      }),
      http.post(`${BASE}/session-1/short-receive`, () => {
        order.push("count");
        counted();
        return HttpResponse.json({
          status: "short_receive_confirmed",
          line_id: "bolts",
          product_name: "Hex Bolt M8",
          received_quantity: 5,
          expected_quantity: 5,
          uom_symbol: "pcs",
          message: "",
          session_complete: true,
        });
      }),
      http.patch(`/api/v1/warehouse/documents/${DOC}/complete`, () =>
        HttpResponse.json({
          id: DOC,
          number: "PZ/2026/015",
          type: "IN",
          status: "COMPLETED",
          reversed_by_id: null,
          lines: [],
        }),
      ),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    const card = await screen.findByRole("region", { name: "Hex Bolt M8" });
    expect(await within(card).findByText("A-02-01")).toBeInTheDocument();
    expect(within(card).getByText("Aisle A, shelf 2")).toBeInTheDocument();
    expect(
      within(card).getByText("The product already lies here"),
    ).toBeInTheDocument();
    expect(within(card).queryByText(/Main Warehouse/)).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Correct, finish receiving" }),
    );
    // What the card said is where the goods are booked: the shelf is named
    // on the line before the count lands.
    await waitFor(() => expect(order).toEqual(["target:shelf-a2", "count"]));
    // The late plans do not take the count back.
    expect(
      await screen.findByRole("heading", { name: "Received 1 line" }),
    ).toBeInTheDocument();
    await act(() => new Promise((resolve) => setTimeout(resolve, 60)));
    expect(
      screen.getByRole("heading", { name: "Received 1 line" }),
    ).toBeInTheDocument();
  });

  it("says why the shelf was refused, and counts nothing onto it", async () => {
    // The catch here once returned quietly, trusting "the mutation's own
    // toast" — `mutateAsync` gets none, so the press simply did nothing.
    serveLocations([
      { id: "wh", name: "Main Warehouse", short_code: "MAIN", is_leaf: false },
      {
        id: "shelf-a2",
        name: "Aisle A, shelf 2",
        parent_id: "wh",
        short_code: "A-02-01",
      },
    ]);
    const bolts = line("bolts", "Hex Bolt M8", {
      expected_quantity: 5,
      planned_location_id: "wh",
      planned_location_name: "Main Warehouse",
      planned_source: "document",
      suggested_location_id: "shelf-a2",
      suggested_location_name: "Aisle A, shelf 2",
      suggested_source: "stock",
    });
    const counted = vi.fn();
    server.use(
      http.post(`${BASE}/start`, () => HttpResponse.json(session([bolts]))),
      http.patch(`/api/v1/warehouse/documents/${DOC}/lines/doc-bolts`, () =>
        HttpResponse.json({ detail: "This shelf is full" }, { status: 400 }),
      ),
      http.post(`${BASE}/session-1/short-receive`, () => {
        counted();
        return HttpResponse.json({});
      }),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    const card = await screen.findByRole("region", { name: "Hex Bolt M8" });
    expect(await within(card).findByText("A-02-01")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Correct, finish receiving" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This shelf is full"),
    );
    expect(counted).not.toHaveBeenCalled();
  });

  it("asks for a shelf when nothing names one, without the plan's jargon", async () => {
    serveDocument();
    serveLocations([
      { id: "wh", name: "Main Warehouse", is_leaf: false },
      {
        id: "shelf-a2",
        name: "Aisle A, shelf 2",
        parent_id: "wh",
        short_code: "A-02-01",
      },
    ]);
    server.use(
      http.post(`${BASE}/start`, () =>
        HttpResponse.json(
          session([
            line("bolts", "Hex Bolt M8", {
              planned_location_id: "wh",
              planned_location_name: "Main Warehouse",
              planned_source: "document",
            }),
          ]),
        ),
      ),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    const card = await screen.findByRole("region", { name: "Hex Bolt M8" });
    const choose = await within(card).findByRole("button", {
      name: "Choose a location",
    });
    expect(within(card).queryByText(/Main Warehouse/)).not.toBeInTheDocument();

    await user.click(choose);
    const picker = within(card).getByRole("combobox");
    // The prompt is what the field says, not a row anybody can pick; and the
    // plan's own words are no choice for the person holding the box.
    expect(picker).toHaveTextContent("Choose a location");
    await user.click(picker);
    expect(
      await screen.findByRole("button", { name: /Aisle A, shelf 2/ }),
    ).toBeInTheDocument();

    expect(
      within(card).queryByText("Follow the plan (rule / document)"),
    ).not.toBeInTheDocument();
  });

  it("finishes without the rest: books what came and offers the document and Undo", async () => {
    serveDocument();
    // A line nothing of which arrived is answered as a short receive of
    // nothing, not skipped: a skip carries no reason, and the completion
    // that follows at once would be refused for it.
    const answered: Array<{ line_id: string; received_quantity: unknown }> = [];
    let skips = 0;
    let completed = false;
    server.use(
      http.post(`${BASE}/start`, () => HttpResponse.json(reopened())),
      http.post(`${BASE}/session-1/skip`, () => {
        skips += 1;
        return HttpResponse.json({ status: "skipped" });
      }),
      http.post(`${BASE}/session-1/short-receive`, async ({ request }) => {
        answered.push(
          (await request.json()) as {
            line_id: string;
            received_quantity: unknown;
          },
        );
        return HttpResponse.json({
          status: "short_receive_confirmed",
          session_complete: false,
        });
      }),
      http.get(`${BASE}/session-1`, () =>
        HttpResponse.json(
          session(
            [
              line("rice", "Jasmine Rice", {
                status: "received",
                received_quantity: 40,
              }),
              line("plums", "Damson Plums", { status: "short" }),
              line("gouda", "Gouda Cheese", { status: "short" }),
            ],
            "completed",
          ),
        ),
      ),
      http.patch(`/api/v1/warehouse/documents/${DOC}/complete`, () => {
        completed = true;
        return HttpResponse.json({
          id: DOC,
          number: "PZ/2026/015",
          type: "IN",
          status: "COMPLETED",
          reversed_by_id: null,
          lines: [],
        });
      }),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    await screen.findByRole("region", { name: "Damson Plums" });
    await user.click(
      screen.getByRole("button", { name: "The rest did not come — finish" }),
    );
    const ask = await screen.findByRole("alertdialog");
    expect(
      within(ask).getByText(/2 lines are not confirmed/),
    ).toBeInTheDocument();
    await user.click(
      within(ask).getByRole("button", { name: "Finish receiving" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Received 1 line" }),
    ).toBeInTheDocument();
    expect(answered.map((a) => [a.line_id, a.received_quantity])).toEqual([
      ["plums", 0],
      ["gouda", 0],
    ]);
    expect(skips).toBe(0);
    expect(completed).toBe(true);
    expect(
      screen.getByText(
        "1 of 3 lines arrived and are in stock. What did not come stays expected on the order.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "PZ/2026/015" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Back to start" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /undo receipt/i }),
    ).toBeInTheDocument();
  });

  /**
   * A delivery whose only line was skipped on the desktop: the phone opens the
   * finished session and used to post the completion at once, got the refusal
   * and offered only Retry — no way to undo the skip or say what became of it.
   */
  async function answerSkippedLines(
    skipped: Array<{
      id: string;
      fromOrder: boolean;
      answer: "OTHER" | "SHORTAGE";
    }>,
    backorder?: { id: string; number: string },
  ) {
    serveDocument();
    const answered: Array<{ line_id: string; code: string }> = [];
    let completions = 0;
    const sessionNow = () =>
      HttpResponse.json(
        session(
          skipped.map((sk) =>
            line(sk.id, sk.id, {
              status: answered.some((a) => a.line_id === sk.id)
                ? "short"
                : "skipped",
              from_order: sk.fromOrder,
            }),
          ),
          "completed",
        ),
      );
    server.use(
      http.post(`${BASE}/start`, sessionNow),
      http.get(`${BASE}/session-1`, sessionNow),
      http.post(`${BASE}/session-1/short-receive`, async ({ request }) => {
        const body = (await request.json()) as {
          line_id: string;
          discrepancy_code: string;
        };
        answered.push({ line_id: body.line_id, code: body.discrepancy_code });
        return HttpResponse.json({
          status: "short_receive_confirmed",
          session_complete: answered.length === skipped.length,
        });
      }),
      http.patch(`/api/v1/warehouse/documents/${DOC}/complete`, () => {
        completions += 1;
        return HttpResponse.json({
          id: DOC,
          number: "PZ/2026/015",
          type: "IN",
          status: "COMPLETED",
          reversed_by_id: null,
          generated_backorder_id: backorder?.id ?? null,
          generated_backorder_number: backorder?.number ?? null,
          // The saved answer of each line, which is what the server acted on.
          lines: skipped.map((sk) => ({
            id: `doc-${sk.id}`,
            discrepancy_code: sk.answer,
          })),
        });
      }),
    );
    const user = userEvent.setup();

    let view = render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    expect(
      (await screen.findAllByRole("button", { name: /undo skip/i })).length,
    ).toBe(skipped.length);
    expect(completions).toBe(0);

    for (const [i, sk] of skipped.entries()) {
      if (i > 0) {
        // An answer takes the worker off the summary: the next line is
        // reached by opening the receipt again, where only it is left.
        view.unmount();
        view = render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
        await screen.findAllByRole("button", { name: /undo skip/i });
      }
      await user.click(
        screen.getAllByRole("button", {
          name: sk.answer === "SHORTAGE" ? /backorder/i : /not coming/i,
        })[0],
      );
      await waitFor(() => expect(answered).toHaveLength(i + 1));
      expect(answered[i]).toEqual({
        line_id: sk.id,
        code: sk.answer,
      });
    }
    await waitFor(() => expect(completions).toBe(1));
  }

  const answerSkippedLine = (opts: {
    fromOrder: boolean;
    backorder?: { id: string; number: string };
  }) =>
    answerSkippedLines(
      [
        {
          id: "plums",
          fromOrder: opts.fromOrder,
          answer: opts.backorder ? "SHORTAGE" : "OTHER",
        },
      ],
      opts.backorder,
    );

  it("hands a delivery finished with a skipped line to the answers, not to a dead end", async () => {
    await answerSkippedLine({ fromOrder: true });
    expect(
      await screen.findByText(
        "0 of 1 lines arrived and are in stock. What did not come stays expected on the order.",
      ),
    ).toBeInTheDocument();
  });

  it("does not say the missing goods stay expected when no order stands behind them", async () => {
    await answerSkippedLine({ fromOrder: false });
    expect(
      await screen.findByText(
        "0 of 1 lines arrived and are in stock. What did not come is closed: nothing is left expected.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/stays expected/)).not.toBeInTheDocument();
  });

  it("names the backorder opened for goods that came without an order", async () => {
    await answerSkippedLine({
      fromOrder: false,
      backorder: { id: "bo-1", number: "PZ/2026/016" },
    });
    expect(
      await screen.findByText(
        "0 of 1 lines arrived and are in stock. What did not come waits on backorder PZ/2026/016.",
      ),
    ).toBeInTheDocument();
  });

  it("does not attribute one line's backorder to a line that was closed", async () => {
    await answerSkippedLines(
      [
        { id: "plums", fromOrder: false, answer: "OTHER" },
        { id: "gouda", fromOrder: false, answer: "SHORTAGE" },
      ],
      { id: "bo-1", number: "PZ/2026/016" },
    );
    expect(
      await screen.findByText(
        "0 of 2 lines arrived and are in stock. Part of what did not come is still expected, the rest is closed: the document shows which.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/waits on backorder/)).not.toBeInTheDocument();
  });

  it("does not call goods closed when one line stays on the order and the other is on a backorder", async () => {
    await answerSkippedLines(
      [
        { id: "plums", fromOrder: true, answer: "OTHER" },
        { id: "gouda", fromOrder: false, answer: "SHORTAGE" },
      ],
      { id: "bo-1", number: "PZ/2026/016" },
    );
    expect(
      await screen.findByText(
        "0 of 2 lines arrived and are in stock. What did not come is still expected: part on the order, part on backorder PZ/2026/016.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/is closed/)).not.toBeInTheDocument();
  });
});

/**
 * A scanner reads faster than the server answers: a warehouse's wifi takes a
 * few hundred milliseconds a round trip, and the scanner fires every few
 * tens. The field used to go dead for each round trip, so a code read in
 * between fell on whatever had the focus — Enter on the Back button paused
 * the session — and the ones that did arrive were dropped by a guard.
 */
describe("a burst of scans on a phone", () => {
  const PRODUCTS = [
    { id: "rice", name: "Jasmine Rice", barcode: "8710000000011" },
    { id: "plums", name: "Damson Plums", barcode: "8710000000028" },
    { id: "gouda", name: "Gouda Cheese", barcode: "8710000000035" },
  ];
  const lines = () =>
    session(PRODUCTS.map((product) => line(product.id, product.name)));
  const field = () =>
    screen.getByRole("textbox", {
      name: "Scan the next product, in any order",
    }) as HTMLInputElement;

  /** The server holds the counts; a scan that only identifies adds none. */
  function serveScans({
    delayMs = 15,
    refuse = [] as string[],
    onScanned = (_barcode: string) => {},
  } = {}) {
    const received: Record<string, number> = {};
    const barcodes: string[] = [];
    server.use(
      http.post(`${BASE}/start`, () => HttpResponse.json(lines())),
      http.post(`${BASE}/session-1/scan`, async ({ request }) => {
        const body = (await request.json()) as {
          barcode: string;
          identify?: boolean;
        };
        barcodes.push(body.barcode);
        onScanned(body.barcode);
        await new Promise((resolve) => setTimeout(resolve, delayMs));
        if (refuse.includes(body.barcode)) {
          return HttpResponse.json({ detail: "down" }, { status: 500 });
        }
        const product = PRODUCTS.find((p) => p.barcode === body.barcode)!;
        if (!body.identify) {
          received[product.id] = (received[product.id] ?? 0) + 1;
        }
        return HttpResponse.json({
          status: "identified",
          line_id: product.id,
          product_name: product.name,
          received_quantity: received[product.id] ?? 0,
          expected_quantity: 10,
          uom_symbol: "pcs",
          message: "",
          session_complete: false,
        });
      }),
    );
    return { received, barcodes };
  }

  it("takes every scan of 30 codes once, in order, and ends on the last card", async () => {
    serveDocument();
    const { received, barcodes } = serveScans();
    const onClose = vi.fn();
    render(<WmsReceivingView documentId={DOC} onClose={onClose} />);
    await screen.findByRole("region", { name: "Jasmine Rice" });

    const fired = Array.from(
      { length: 30 },
      (_, i) => PRODUCTS[i % PRODUCTS.length].barcode,
    );
    // No await between the codes: a scanner does not wait for the screen.
    for (const code of fired) scanIntoField(code, field());

    await waitFor(() => expect(barcodes).toHaveLength(30), { timeout: 5000 });
    expect(barcodes).toEqual(fired);
    // The last code read was the cheese's: its card is the one in hand.
    expect(
      await screen.findByRole("region", { name: "Gouda Cheese" }),
    ).toBeInTheDocument();
    // Identifying counted nothing, however many times it was asked.
    expect(received).toEqual({});
    expect(onClose).not.toHaveBeenCalled();
  });

  it("says which scans the server did not record and keeps the counts it holds", async () => {
    serveDocument();
    const { barcodes } = serveScans({ refuse: [PRODUCTS[1].barcode] });
    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    await screen.findByRole("region", { name: "Jasmine Rice" });

    for (const product of [PRODUCTS[0], PRODUCTS[1], PRODUCTS[2]]) {
      scanIntoField(product.barcode, field());
    }

    await waitFor(() => expect(barcodes).toHaveLength(3));
    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent(
      `Not recorded, scan again: ${PRODUCTS[1].barcode}`,
    );
    // The scan after the refused one still went through.
    expect(
      await screen.findByRole("region", { name: "Gouda Cheese" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Still due 10 pcs\./)).toBeInTheDocument();
  });

  it("sends the scans still queued before it lets the worker leave", async () => {
    serveDocument();
    const user = userEvent.setup();
    const { barcodes } = serveScans({ delayMs: 60 });
    const onClose = vi.fn();
    render(<WmsReceivingView documentId={DOC} onClose={onClose} />);
    await screen.findByRole("region", { name: "Jasmine Rice" });

    scanIntoField(PRODUCTS[1].barcode, field());
    scanIntoField(PRODUCTS[2].barcode, field());
    await user.click(screen.getByRole("button", { name: "Back" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    // By the time the view closed, both scans had been answered.
    expect(barcodes).toEqual([PRODUCTS[1].barcode, PRODUCTS[2].barcode]);
  });
});

describe("a scan the delivery does not take, on a phone", () => {
  const field = () =>
    screen.getByRole("textbox", {
      name: "Scan the next product, in any order",
    }) as HTMLInputElement;

  function serveAnswer(answer: Record<string, unknown>) {
    serveDocument();
    server.use(
      http.post(`${BASE}/start`, () =>
        HttpResponse.json(session([line("plums", "Damson Plums")])),
      ),
      http.post(`${BASE}/session-1/scan`, () =>
        HttpResponse.json({
          line_id: null,
          received_quantity: 0,
          expected_quantity: 0,
          uom_symbol: null,
          message: "",
          session_complete: false,
          ...answer,
        }),
      ),
    );
  }

  beforeEach(() => {
    vi.mocked(toast.error).mockClear();
    Object.defineProperty(navigator, "vibrate", {
      value: vi.fn(),
      configurable: true,
    });
  });

  it("names the product that is not on the delivery beside the field, says where it is received, and buzzes", async () => {
    serveAnswer({
      status: "not_in_document",
      product_name: "APC Smart-UPS 3000VA",
    });
    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    await screen.findByRole("region", { name: "Damson Plums" });

    scanIntoField("7000000000001", field());

    // A confirmed receipt takes no new line: the way on is a receipt of its own.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "APC Smart-UPS 3000VA is not on this delivery. Finish this one, then receive it on a new receipt from Receive goods.",
    );
    // Not a toast over the title: the sentence stays beside the field.
    expect(toast.error).not.toHaveBeenCalled();
    // A pattern, not the single short buzz a good scan gives.
    expect(navigator.vibrate).toHaveBeenCalledWith([80, 60, 80]);
  });

  it("asks the receiver to wait when the item scans come faster than the API takes them", async () => {
    serveDocument();
    server.use(
      http.post(`${BASE}/start`, () =>
        HttpResponse.json(session([line("plums", "Damson Plums")])),
      ),
      http.post(`${BASE}/session-1/scan`, () =>
        HttpResponse.json(
          { detail: "Too many requests. Try again later." },
          { status: 429 },
        ),
      ),
    );
    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    await screen.findByRole("region", { name: "Damson Plums" });

    scanIntoField("7000000000003", field());

    expect(
      await screen.findByText(
        "Too many scans in a minute. Wait a moment, then scan again.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Too many requests. Try again later."),
    ).not.toBeInTheDocument();
  });

  it("says how much of an already received line came", async () => {
    serveAnswer({
      status: "already_received",
      product_name: "ThinkPad T14s",
      received_quantity: 2,
      expected_quantity: 2,
      uom_symbol: "pcs",
    });
    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    await screen.findByRole("region", { name: "Damson Plums" });

    scanIntoField("7000000000002", field());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ThinkPad T14s already received: 2 of 2 pcs.",
    );
    expect(navigator.vibrate).toHaveBeenCalledWith([80, 60, 80]);
  });

  it("keeps a code that matches no product as its own message, without the refusal", async () => {
    serveAnswer({ status: "not_found" });
    render(<WmsReceivingView documentId={DOC} onClose={vi.fn()} />);
    await screen.findByRole("region", { name: "Damson Plums" });

    scanIntoField("0000000000000", field());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error).mock.calls[0][0]).toBe(
      "No product has the code 0000000000000",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
