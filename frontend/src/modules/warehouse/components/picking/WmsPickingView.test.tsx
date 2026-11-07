import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  render as rtlRender,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import { toast } from "sonner";
import {
  insertScanIntoField,
  pauseBeforeScan,
  scanIntoField,
  scanWithHardwareScanner,
} from "@/test/scanner";
import WmsPickingView from "./WmsPickingView";
import type { WmsPickSession } from "@/modules/warehouse/api/documents";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  }),
}));

// The camera is a live device; the screens are what these tests read.
const cameraMock = vi.hoisted(() => ({
  onCodeScanned: (_code: string) => {},
  scannerError: null as string | null,
  restartCamera: vi.fn(),
  setIsCameraActive: vi.fn(),
  toggleTorch: vi.fn(),
}));

vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: ({
    onCodeScanned,
  }: {
    onCodeScanned: (code: string) => void;
  }) => {
    cameraMock.onCodeScanned = onCodeScanned;
    return {
      scannerError: cameraMock.scannerError,
      isCameraActive: true,
      isCameraRunning: true,
      setIsCameraActive: cameraMock.setIsCameraActive,
      restartCamera: cameraMock.restartCamera,
      startCamera: vi.fn(),
      resumeCamera: vi.fn(),
      pauseCamera: vi.fn(),
      toggleTorch: cameraMock.toggleTorch,
      isTorchOn: false,
    };
  },
}));

beforeEach(() => {
  cameraMock.scannerError = null;
  cameraMock.restartCamera.mockReset();
  cameraMock.setIsCameraActive.mockReset();
  cameraMock.toggleTorch.mockReset();
});

const DOCUMENT_ID = "doc-1";
const START_PATH = `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/start`;

function buildSession(): WmsPickSession {
  return {
    id: "session-1",
    document_id: DOCUMENT_ID,
    assigned_to: null,
    status: "active",
    started_at: "2026-04-05T08:00:00Z",
    completed_at: null,
    total_lines: 1,
    picked_lines: 0,
    pending_lines: 1,
    shelf_scan_required: false,
    documents: [],
    lines: [
      {
        id: "pick-line-1",
        document_line_id: "line-1",
        pick_order: 1,
        status: "pending",
        picked_quantity: 0,
        bin_location: "A-01-02",
        product_name: "Widget",
        lot_name: null,
        expected_quantity: 5,
        uom_symbol: "pcs",
      },
    ],
  };
}

/** The only line picked in full, which ends the session on its summary. */
function pickedInFull() {
  return http.post(
    `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/short-pick`,
    () =>
      HttpResponse.json({
        status: "short_pick_confirmed",
        line_id: "pick-line-1",
        product_name: "Widget",
        picked_quantity: 5,
        expected_quantity: 5,
        uom_symbol: "pcs",
        session_complete: true,
        message: "",
      }),
  );
}

/** The view refreshes the document behind it when a session ends. */
function render(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return rtlRender(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  });
}

describe("WmsPickingView", () => {
  it.each([
    ["rejected", "This document was completed or cancelled.", true],
    ["all_picked", "All lines have already been picked.", false],
  ])("announces the %s scan response", async (status, message, rejected) => {
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast).mockClear();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () => HttpResponse.json({ status, session_complete: false }),
      ),
    );
    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    invalidate.mockClear();
    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "1234567890123{enter}",
    );
    await waitFor(() =>
      expect(rejected ? toast.error : toast).toHaveBeenCalledWith(message),
    );
    if (rejected) expect(invalidate).toHaveBeenCalled();
    invalidate.mockRestore();
  });
  it("announces the sheet in the reader's language, not in English", async () => {
    // The sheet's aria-label and the heading under it are one catalogue key,
    // and in Polish that key said "Picking" — the name a screen reader read
    // out as the window, above Polish progress and a Polish scan prompt.
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    await withLanguage("pl", async () => {
      render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

      expect(
        await screen.findByRole("dialog", { name: "Kompletacja" }),
      ).toBeInTheDocument();
      expect(screen.getByText("Kompletacja")).toBeInTheDocument();
      expect(screen.queryByText("Picking")).not.toBeInTheDocument();
    });
  });

  it("lets a product name without spaces wrap in the text under the scan field", async () => {
    const name =
      "Supercalifragilisticexpialidociousproductnamewithoutspaces123456";
    const session = buildSession();
    session.lines[0] = { ...session.lines[0], product_name: name };
    server.use(http.post(START_PATH, () => HttpResponse.json(session)));
    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    const next = await screen.findByText(`${name} — 5 pcs.`);
    expect(next).toHaveClass("[overflow-wrap:anywhere]");
  });

  it("starts the session on mount and shows the line to pick", async () => {
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    expect(await screen.findByText("Widget — 5 pcs.")).toBeInTheDocument();
    expect(screen.getByText("Picking")).toBeInTheDocument();
    expect(screen.getByText("Go to A-01-02")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Scan barcode or type…"),
    ).toBeInTheDocument();
  });

  it("keeps link colour off the shelf line, which opens nothing", async () => {
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    const goTo = await screen.findByText("Go to A-01-02");
    expect(goTo.closest("a, button")).toBeNull();
    expect(goTo.className).not.toMatch(/text-primary/);
  });

  it("closes with a 44 px target, not the compact 32 px one", async () => {
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    const close = screen.getByRole("button", { name: "Close" });
    expect(close).toHaveClass("h-11", "w-11");
    expect(close).not.toHaveClass("h-8");
  });

  it("explains a 409 APPROVAL_REQUIRED instead of rendering nothing", async () => {
    server.use(
      http.post(START_PATH, () =>
        HttpResponse.json(
          {
            detail: {
              code: "APPROVAL_REQUIRED",
              message: "Document requires approval",
            },
          },
          { status: 409 },
        ),
      ),
    );
    const onRequestApproval = vi.fn();

    render(
      <WmsPickingView
        documentId={DOCUMENT_ID}
        onClose={vi.fn()}
        onRequestApproval={onRequestApproval}
      />,
    );

    expect(
      await screen.findByText(
        "This document requires approval before picking can start. Requesting it moves the document back to awaiting approval, where it stays until someone signs off.",
      ),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Request approval" }),
    );
    expect(onRequestApproval).toHaveBeenCalledTimes(1);
    // Retrying the same start would fail the same way — only the approval
    // route out is offered.
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("offers a retry when the start fails for any other reason", async () => {
    let starts = 0;
    server.use(
      http.post(START_PATH, () => {
        starts += 1;
        return HttpResponse.json({ detail: "Boom" }, { status: 500 });
      }),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    expect(
      await screen.findByText("Failed to start the picking session."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Request approval" }),
    ).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(starts).toBe(2));
  });

  it("speaks the namespace's sentence when the scan cannot be recorded", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "1234567890123{enter}",
    );

    // The hook no longer carries a fallback sentence of its own, so the
    // words come from the namespace — not "Scan failed" over Polish buttons.
    expect(
      await screen.findByText("Failed to record the scan."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Scan failed")).not.toBeInTheDocument();
  });

  it("says where to give the product the code a scan did not find", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () =>
          HttpResponse.json({
            status: "not_found",
            message: "Product not recognized",
          }),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "5901234123457{enter}",
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "No product has the code 5901234123457",
        {
          description:
            "Give it to the product in its edit form, in the “Product code” field, then scan again.",
        },
      ),
    );
  });

  it("asks for the shelf first and marks the line once its label is scanned", async () => {
    const session = buildSession();
    session.shelf_scan_required = true;
    session.confirmed_shelf_id = null;
    session.lines[0].location_id = "shelf-a";
    session.lines[0].location_code = "A-01";
    const answers = [
      {
        status: "shelf_required",
        shelf: "A-01 · Rack A",
        shelf_id: "shelf-a",
        message: "",
      },
      {
        status: "shelf_confirmed",
        shelf: "A-01 · Rack A",
        shelf_id: "shelf-a",
        message: "",
      },
    ];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(session)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () => HttpResponse.json(answers.shift()),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    expect(screen.getByText("Scan the location label")).toBeInTheDocument();

    const field = screen.getByPlaceholderText("Scan barcode or type…");
    await userEvent.type(field, "5901234123457{enter}");
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Scan the location first: A-01 · Rack A",
      ),
    );

    await userEvent.type(field, "SHF-A1{enter}");
    expect(await screen.findByText("Location confirmed")).toBeInTheDocument();
    expect(
      screen.queryByText("Scan the location label"),
    ).not.toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith(
      "Location A-01 · Rack A confirmed",
    );
  });

  it("asks for the destination label after the last line of a transfer and ends on the right one", async () => {
    const session = buildSession();
    session.shelf_scan_required = true;
    session.destination_shelf_id = "shelf-c";
    session.destination_shelf = "C-03 · Rack C";
    const answers = [
      {
        status: "picked",
        line_id: "pick-line-1",
        picked_quantity: 5,
        expected_quantity: 5,
        session_complete: false,
        message: "",
      },
      {
        status: "wrong_shelf",
        shelf: "C-03 · Rack C",
        shelf_id: "shelf-c",
        session_complete: false,
        message: "",
      },
      {
        status: "shelf_confirmed",
        shelf: "C-03 · Rack C",
        shelf_id: "shelf-c",
        session_complete: true,
        message: "",
      },
    ];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(session)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () => HttpResponse.json(answers.shift()),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "5901234123457{enter}",
    );

    const field = await screen.findByPlaceholderText(
      "Scan the destination location label…",
    );
    expect(
      screen.getByText("Take the goods to C-03 · Rack C and scan its label"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Complete picking" }),
    ).toBeDisabled();

    await userEvent.type(field, "SHF-B2{enter}");
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "That is not the location — go to C-03 · Rack C",
      ),
    );
    expect(
      screen.getByPlaceholderText("Scan the destination location label…"),
    ).toBeInTheDocument();

    await userEvent.type(field, "DST-C3{enter}");
    await waitFor(() =>
      expect(
        screen.queryByPlaceholderText("Scan the destination location label…"),
      ).not.toBeInTheDocument(),
    );
    expect(toast.success).toHaveBeenCalledWith(
      "Location C-03 · Rack C confirmed",
    );
  });

  it("keeps the sheet open after skipping the last line when a destination is awaited", async () => {
    const session = buildSession();
    session.shelf_scan_required = true;
    session.destination_shelf_id = "shelf-c";
    session.destination_shelf = "C-03 · Rack C";
    session.lines = [
      { ...session.lines[0], status: "picked", picked_quantity: 5 },
      {
        ...session.lines[0],
        id: "pick-line-2",
        document_line_id: "line-2",
        product_name: "Gadget",
      },
    ];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(session)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/skip`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Gadget — 5 pcs.");
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Skip" }));

    expect(
      await screen.findByPlaceholderText(
        "Scan the destination location label…",
      ),
    ).toBeInTheDocument();
  });

  it("takes the confirmation back when another location's label is scanned", async () => {
    const session = buildSession();
    session.shelf_scan_required = true;
    session.confirmed_shelf_id = null;
    session.lines[0].location_id = "shelf-a";
    session.lines[0].location_code = "A-01";
    const answers = [
      {
        status: "shelf_confirmed",
        shelf: "A-01 · Rack A",
        shelf_id: "shelf-a",
        message: "",
      },
      {
        status: "wrong_shelf",
        shelf: "A-01 · Rack A",
        shelf_id: "shelf-a",
        message: "",
      },
    ];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(session)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () => HttpResponse.json(answers.shift()),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    const field = screen.getByPlaceholderText("Scan barcode or type…");
    await userEvent.type(field, "SHF-A1{enter}");
    expect(await screen.findByText("Location confirmed")).toBeInTheDocument();

    await userEvent.type(field, "SHF-B2{enter}");
    expect(
      await screen.findByText("Scan the location label"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Location confirmed")).not.toBeInTheDocument();
  });

  it("asks the picker to wait when the scans come faster than the API takes them", async () => {
    // Past the per-minute ceiling the API answers 429 with a generic
    // "try again later"; the scan screen says what to do right now instead.
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () =>
          HttpResponse.json(
            { detail: "Too many requests. Try again later." },
            { status: 429 },
          ),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "1234567890123{enter}",
    );

    expect(
      await screen.findByText(
        "Too many scans in a minute. Wait a moment, then scan again.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Too many requests. Try again later."),
    ).not.toBeInTheDocument();
  });

  it("sends the quantity the picker declared, and keeps the line open", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          bodies.push(body);
          return HttpResponse.json({
            status: "picked",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 2,
            expected_quantity: 5,
            uom_symbol: "pcs",
            bin_location: "A-01-02",
            session_complete: false,
            message: "",
          });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.clear(screen.getByLabelText("Quantity"));
    await userEvent.type(screen.getByLabelText("Quantity"), "2");
    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "1234567890123{enter}",
    );

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      barcode: "1234567890123",
      quantity: 2,
    });
    // two of five in hand leaves three to fetch — the line stays the next
    // one to scan instead of closing on the first read.
    expect(await screen.findByText("Widget — 2/5 pcs.")).toBeInTheDocument();
  });

  it("records a pick from a hardware scanner while the focus is off the field", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "picked",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 1,
            expected_quantity: 5,
            uom_symbol: "pcs",
            bin_location: "A-01-02",
            session_complete: false,
            message: "",
          });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    expect(
      screen.getByText("A barcode scanner can be used on this screen"),
    ).toBeInTheDocument();

    // The picker tapped somewhere else; the scanner types at the page.
    (document.activeElement as HTMLElement | null)?.blur();
    scanWithHardwareScanner("1234567890123", document.body);

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ barcode: "1234567890123", quantity: 1 });
    expect(await screen.findByText("Widget — 1/5 pcs.")).toBeInTheDocument();
    expect(toast.success).toHaveBeenCalled();
  });

  it.each([
    ["a keyboard-wedge burst", scanIntoField],
    ["a scanning keyboard's single insertion", insertScanIntoField],
  ])(
    "takes a pick with the quantity typed before it from %s",
    async (_name, scanInto) => {
      const bodies: Array<Record<string, unknown>> = [];
      server.use(
        http.post(START_PATH, () => HttpResponse.json(buildSession())),
        http.post(
          `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
          async ({ request }) => {
            bodies.push((await request.json()) as Record<string, unknown>);
            return HttpResponse.json({
              status: "picked",
              line_id: "pick-line-1",
              product_name: "Widget",
              picked_quantity: 20,
              expected_quantity: 5,
              uom_symbol: "pcs",
              bin_location: "A-01-02",
              session_complete: false,
              message: "",
            });
          },
        ),
      );

      render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
      await screen.findByText("Widget — 5 pcs.");

      const quantity = screen.getByRole("spinbutton", { name: "Quantity" });
      await userEvent.clear(quantity);
      await userEvent.type(quantity, "20");
      expect(quantity).toHaveValue(20);
      // A person's pause before the trigger; the scanner's keys are 50 ms
      // apart at most, and the test's own keys come faster than a hand.
      pauseBeforeScan();

      scanInto("1234567890123", quantity as HTMLInputElement);

      await waitFor(() => expect(bodies).toHaveLength(1));
      expect(bodies[0]).toMatchObject({
        barcode: "1234567890123",
        quantity: 20,
      });
    },
  );

  it("keeps a quantity typed by hand, digit by digit, and does not scan it", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "picked",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 20,
            expected_quantity: 5,
            uom_symbol: "pcs",
            bin_location: "A-01-02",
            session_complete: false,
            message: "",
          });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    const quantity = screen.getByRole("spinbutton", { name: "Quantity" });
    await userEvent.clear(quantity);
    // A hand is slower than 50 ms a key; user-event's default is not.
    await userEvent.setup({ delay: 80 }).type(quantity, "12345{Enter}");

    expect(quantity).toHaveValue(12345);
    expect(bodies).toHaveLength(0);
  });

  it("opens the camera from an empty Scan and records the code it reads", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "picked",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 1,
            expected_quantity: 5,
            uom_symbol: "pcs",
            bin_location: "A-01-02",
            session_complete: false,
            message: "",
          });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    expect(document.getElementById("qr-reader")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Scan" }));

    expect(cameraMock.restartCamera).toHaveBeenCalled();
    expect(document.getElementById("qr-reader")).not.toBeNull();

    // The camera calls back from outside React, as the decoder does.
    await act(async () => cameraMock.onCodeScanned("1234567890123"));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      barcode: "1234567890123",
      quantity: 1,
    });
    // The pick is recorded exactly as the same code typed and confirmed.
    expect(await screen.findByText("Widget — 1/5 pcs.")).toBeInTheDocument();
  });

  it("says why the empty Scan cannot open a camera instead of doing nothing", async () => {
    cameraMock.scannerError =
      "No camera was found on this device. Connect a camera or use a different device.";
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({ status: "not_found", message: "" });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(screen.getByRole("button", { name: "Scan" }));

    expect(
      await screen.findByText(
        "No camera was found on this device. Connect a camera or use a different device.",
      ),
    ).toBeInTheDocument();
    // Nothing was scanned: an empty field never becomes an empty request.
    expect(bodies).toHaveLength(0);
  });

  it("records one pick when the scanner reads the same code twice", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({ status: "not_found", message: "" });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    // A double read: the same code twice, a few ms apart.
    (document.activeElement as HTMLElement | null)?.blur();
    scanWithHardwareScanner("1234567890123", document.body);
    scanWithHardwareScanner("1234567890123", document.body);

    await waitFor(() => expect(bodies).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(bodies).toHaveLength(1);
  });

  it("takes a scan typed into the barcode field once, not twice", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({ status: "not_found", message: "" });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    const field = await screen.findByPlaceholderText("Scan barcode or type…");

    // The characters land in the field, as a scanner's do; the Enter that
    // closes the burst must not submit them a second time. Typed by hand the
    // burst is as fast as the machine, and on a loaded one it used to split.
    scanIntoField("1234567890123", field as HTMLInputElement);

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ barcode: "1234567890123" });
    expect(field).toHaveValue("");
  });

  it("keeps a batch label scanned into the batch field out of the product scan", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "picked",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 1,
            expected_quantity: 5,
            uom_symbol: "pcs",
            bin_location: "A-01-02",
            session_complete: false,
            message: "",
          });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "1234567890123",
    );
    // The label's code is read with the focus in the batch field: it is the
    // batch of the product above, not a product of its own.
    scanIntoField(
      "LOT2026",
      screen.getByLabelText(
        "Batch code on the label (optional)",
      ) as HTMLInputElement,
    );

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      barcode: "1234567890123",
      lot_name: "LOT2026",
    });
  });

  it("names the planned batch on the step in hand, where the picker reads the label", async () => {
    const planned = buildSession();
    planned.lines[0].lot_name = "LOT-SECOND";
    server.use(http.post(START_PATH, () => HttpResponse.json(planned)));

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    // The step above the scan field says it as well as the row of the list.
    expect(
      screen.getAllByText(/Lot: LOT-SECOND/).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("names the batch the row plans, and sends the code the picker read", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    const planned = buildSession();
    planned.lines[0].lot_name = "LOT-SECOND";
    server.use(
      http.post(START_PATH, () => HttpResponse.json(planned)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "picked",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 5,
            expected_quantity: 5,
            uom_symbol: "pcs",
            bin_location: "A-01-02",
            lot_name: "LOT-FIRST",
            planned_lot_name: "LOT-SECOND",
            session_complete: false,
            message: "",
          });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    expect(screen.getByText("Lot: LOT-SECOND")).toBeInTheDocument();

    await userEvent.type(
      screen.getByLabelText("Batch code on the label (optional)"),
      "LOT-FIRST",
    );
    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "1234567890123{enter}",
    );

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ lot_name: "LOT-FIRST" });
    // The scan is recorded, and the picker is told the plan said otherwise
    // -- the warning the server's note used to be, which no screen showed.
    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith(
        "Lot LOT-FIRST was picked, but the plan said LOT-SECOND — the books follow LOT-FIRST",
      ),
    );
    expect(await screen.findByText("Lot: LOT-FIRST")).toBeInTheDocument();
  });

  it("refuses in words a batch code the line cannot be picked from", async () => {
    const planned = buildSession();
    planned.lines[0].lot_name = "LOT-SECOND";
    server.use(
      http.post(START_PATH, () => HttpResponse.json(planned)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () =>
          HttpResponse.json({
            status: "wrong_lot",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 0,
            expected_quantity: 5,
            lot_name: "LOT-SECOND",
            message: "",
          }),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.type(
      screen.getByLabelText("Batch code on the label (optional)"),
      "NOPE",
    );
    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "1234567890123{enter}",
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Lot NOPE cannot be picked for this line — it expects LOT-SECOND",
      ),
    );
    expect(screen.getByText("Widget — 5 pcs.")).toBeInTheDocument();
  });

  it("does not promise a batch when the line has none", async () => {
    const planned = buildSession();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(planned)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () =>
          HttpResponse.json({
            status: "wrong_lot",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 0,
            expected_quantity: 5,
            lot_name: null,
            message: "",
          }),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.type(
      screen.getByLabelText("Batch code on the label (optional)"),
      "NOPE",
    );
    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "1234567890123{enter}",
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Lot NOPE cannot be picked for this line — no batch is expected here, scan without a batch code",
      ),
    );
    expect(screen.getByText("Widget — 5 pcs.")).toBeInTheDocument();
  });

  it("says a batch is too small, not that it is the wrong one", async () => {
    const planned = buildSession();
    planned.lines[0].lot_name = "LOT-SECOND";
    server.use(
      http.post(START_PATH, () => HttpResponse.json(planned)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () =>
          HttpResponse.json({
            status: "lot_too_small",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 0,
            expected_quantity: 5,
            lot_name: "LOT-SECOND",
            message: "",
          }),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.type(
      screen.getByPlaceholderText("Scan barcode or type…"),
      "1234567890123{enter}",
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Lot LOT-SECOND does not have enough left for this line — scan the label of the next lot for the rest",
      ),
    );
  });

  it("opens the shortfall form from the row's Short pick action", async () => {
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(screen.getByRole("button", { name: "Short pick" }));

    expect(
      await screen.findByRole("heading", { name: "Short pick" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Final picked quantity")).toBeInTheDocument();
  });

  it("records the whole line in one tap, the way a scan in full reports it", async () => {
    vi.mocked(toast.success).mockClear();
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/short-pick`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "short_pick_confirmed",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 5,
            expected_quantity: 5,
            uom_symbol: "pcs",
            bin_location: "A-01-02",
            session_complete: false,
            message: "",
          });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(
      screen.getByRole("button", { name: "Pick full amount" }),
    );

    // The document's own expectation travels as the line's final total, and
    // no discrepancy goes with it — a full pick carries none.
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      line_id: "pick-line-1",
      picked_quantity: 5,
    });
    expect(bodies[0].discrepancy_code).toBeUndefined();
    expect(bodies[0].replace_scans).toBe(false);
    // What the same quantity scanned in full would have said.
    expect(toast.success).toHaveBeenCalledWith("Widget — 5 pcs. picked");
    expect(await screen.findByText("Picked")).toBeInTheDocument();
    expect(screen.queryByLabelText("Final picked quantity")).toBeNull();
  });

  it("opens no shortfall sheet when a line itself is tapped", async () => {
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(screen.getByText("Widget"));

    // Tapping the line used to be the only way to record it, and it opened
    // the shortage window at 0.
    expect(
      screen.queryByRole("heading", { name: "Short pick" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Final picked quantity"),
    ).not.toBeInTheDocument();

    // The shortfall form is still there, behind its own button.
    await userEvent.click(screen.getByRole("button", { name: "Short pick" }));
    expect(
      await screen.findByRole("heading", { name: "Short pick" }),
    ).toBeInTheDocument();
  });

  it("skips a line from the row's Skip action", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/skip`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    // The skip asks first; nothing is sent until it is confirmed.
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Skip" }));

    // One line, skipped — the session closes and the summary says so.
    expect(await screen.findByText("1 skipped")).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Scan barcode or type…"),
    ).not.toBeInTheDocument();
  });

  /** Skip the only line, which ends the session on its summary. */
  async function skipTheLastLine() {
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Skip" }));
    await screen.findByText("1 skipped");
  }

  const SKIP_PATH = `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/skip`;

  it("takes the skip of the last line back from the summary", async () => {
    const undone = vi.fn();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(SKIP_PATH, () => new HttpResponse(null, { status: 204 })),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/undo`,
        ({ request }) => {
          undone(new URL(request.url).searchParams.get("line_id"));
          return HttpResponse.json({
            line_id: "pick-line-1",
            product_name: "Widget",
            restored_quantity: 0,
          });
        },
      ),
    );
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await skipTheLastLine();
    await userEvent.click(screen.getByRole("button", { name: "Undo skip" }));

    // Back on the list, the line to pick again; nothing was completed.
    expect(
      await screen.findByPlaceholderText("Scan barcode or type…"),
    ).toBeInTheDocument();
    expect(undone).toHaveBeenCalledWith("pick-line-1");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("completes a skipped line only with the outcome the person chose", async () => {
    const answered = vi.fn();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(SKIP_PATH, () => new HttpResponse(null, { status: 204 })),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/short-pick`,
        async ({ request }) => {
          answered(await request.json());
          return HttpResponse.json({
            status: "short_pick_confirmed",
            line_id: "pick-line-1",
            product_name: "Widget",
            picked_quantity: 0,
            expected_quantity: 5,
            uom_symbol: "pcs",
            session_complete: true,
            message: "Short pick: 0/5",
          });
        },
      ),
    );
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await skipTheLastLine();
    // Closing first is refused: the skip is not yet an answer.
    await userEvent.click(
      screen.getByRole("button", { name: "Complete and book" }),
    );
    expect(onClose).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Not sent" }));
    await screen.findByText(/· Not sent$/);
    await userEvent.click(
      screen.getByRole("button", { name: "Complete and book" }),
    );

    expect(answered).toHaveBeenCalledWith(
      expect.objectContaining({
        line_id: "pick-line-1",
        picked_quantity: 0,
        discrepancy_code: "OTHER",
      }),
    );
    expect(onClose).toHaveBeenCalledWith(true, undefined);
  });

  it("keeps the line when the skip question is declined", async () => {
    const skipped = vi.fn();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/skip`,
        () => {
          skipped();
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(skipped).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Skip" })).toBeInTheDocument();
  });

  it("closes a finished dispatch with the carrier it leaves with", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      pickedInFull(),
    );
    const onClose = vi.fn();

    render(
      <WmsPickingView
        documentId={DOCUMENT_ID}
        onClose={onClose}
        onPack={vi.fn()}
      />,
    );
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.click(
      screen.getByRole("button", { name: "Pick full amount" }),
    );
    await userEvent.type(await screen.findByLabelText("Carrier"), "DPD");
    await userEvent.type(screen.getByLabelText("Tracking number"), "X2");
    await userEvent.click(
      screen.getByRole("button", { name: "Complete and book" }),
    );

    expect(onClose).toHaveBeenCalledWith(true, {
      carrier: "DPD",
      tracking_number: "X2",
    });
  });

  it("asks a transfer for no carrier when its picking closes", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      pickedInFull(),
    );
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.click(
      screen.getByRole("button", { name: "Pick full amount" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Complete and book" }),
    );

    expect(screen.queryByLabelText("Carrier")).not.toBeInTheDocument();
    expect(onClose).toHaveBeenCalledWith(true, undefined);
  });

  it("reopens on the summary of a session that finished without completing the document", async () => {
    // The summary was left by the back arrow or a closed tab; the start
    // hands that session back instead of a fresh one at 0 of N.
    const finished = buildSession();
    finished.status = "completed";
    finished.picked_lines = 1;
    finished.pending_lines = 0;
    finished.lines = [
      { ...finished.lines[0], status: "picked", picked_quantity: 5 },
    ];
    server.use(http.post(START_PATH, () => HttpResponse.json(finished)));
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);

    expect(await screen.findByText("Picking complete")).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Scan barcode or type…"),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Complete and book" }),
    );
    expect(onClose).toHaveBeenCalledWith(true, undefined);
  });

  it("keeps the dispatch open, as picked, when the summary is left by Escape", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      pickedInFull(),
    );
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.click(
      screen.getByRole("button", { name: "Pick full amount" }),
    );
    await screen.findByText("Picking complete");
    await userEvent.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledWith(false);
  });

  it("leaves a finished dispatch for packing without completing it", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      pickedInFull(),
    );
    const onClose = vi.fn();
    const onPack = vi.fn();
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <WmsPickingView
          documentId={DOCUMENT_ID}
          onClose={onClose}
          onPack={onPack}
        />
      </QueryClientProvider>,
    );
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.click(
      screen.getByRole("button", { name: "Pick full amount" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Pack" }));

    expect(onPack).toHaveBeenCalledOnce();
    // `onClose(true)` is what completes the document behind the sheet.
    expect(onClose).not.toHaveBeenCalled();
    // The Pack step reads the picked quantities from the document, which the
    // session closing by itself left stale.
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["documents", DOCUMENT_ID],
    });
  });

  it("reads the documents again as soon as the session is complete, before a link is followed", async () => {
    // The summary links to each dispatch the session covered; the last scan
    // closes the session with no handler of ours, and those pages would open
    // from the cache as they were before the picking.
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      pickedInFull(),
    );
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    rtlRender(
      <QueryClientProvider client={queryClient}>
        <WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.click(
      screen.getByRole("button", { name: "Pick full amount" }),
    );
    await screen.findByText("Picking complete");

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["documents"] });
  });

  it("asks before discarding a session in which something is already picked", async () => {
    const started = buildSession();
    started.lines[0].picked_quantity = 2;
    const cancelled = vi.fn();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(started)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/cancel`,
        () => {
          cancelled();
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Discard scans" }),
    );

    const dialog = await screen.findByRole("alertdialog");
    expect(cancelled).not.toHaveBeenCalled();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(cancelled).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Discard scans",
      }),
    );
    await waitFor(() => expect(cancelled).toHaveBeenCalledOnce());
    await waitFor(() => expect(onClose).toHaveBeenCalledWith());
  });

  it("does not ask for the label of a location that has no code", async () => {
    // The organization's main warehouse is seeded without a code: there is no
    // label to print for it, so the line is picked without one.
    const session = buildSession();
    session.shelf_scan_required = true;
    session.lines[0].location_id = "main-warehouse";
    server.use(http.post(START_PATH, () => HttpResponse.json(session)));

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    expect(
      screen.queryByText("Scan the location label"),
    ).not.toBeInTheDocument();
  });

  it("names the holder of a held document and can release their session", async () => {
    // The picking twin of the receiving release: the refusal names the
    // holder, and the release goes through the release door with the carried
    // session id, then starts the reader's own session.
    let starts = 0;
    const cancelled: string[] = [];
    server.use(
      http.post(START_PATH, () => {
        starts += 1;
        if (starts === 1) {
          return HttpResponse.json(
            {
              detail: {
                code: "SESSION_HELD_BY_OTHER_USER",
                message: "Another user has an active session on this document.",
                held_session_id: "held-session-9",
                held_by: "Anna Kowalska",
              },
            },
            { status: 409 },
          );
        }
        return HttpResponse.json(buildSession());
      }),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/held-session-9/release`,
        () => {
          cancelled.push("held-session-9");
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    expect(
      await screen.findByText(/Anna Kowalska has an active picking session/),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Discard Anna Kowalska's scans and start over",
      }),
    );

    await waitFor(() => expect(cancelled).toEqual(["held-session-9"]));
    expect(await screen.findByText("Widget — 5 pcs.")).toBeInTheDocument();
    expect(starts).toBe(2);
  });

  it("takes a held session over and continues on its scans", async () => {
    // The hand-over keeps the holder's scans: nothing is cancelled, the
    // session moves through its own door, and the start that follows hands
    // it back as the reader's own.
    let starts = 0;
    const tookOver: string[] = [];
    const cancelled: string[] = [];
    server.use(
      http.post(START_PATH, () => {
        starts += 1;
        if (starts === 1) {
          return HttpResponse.json(
            {
              detail: {
                code: "SESSION_HELD_BY_OTHER_USER",
                message: "Another user has an active session on this document.",
                held_session_id: "held-session-9",
                held_by: "Anna Kowalska",
              },
            },
            { status: 409 },
          );
        }
        return HttpResponse.json(buildSession());
      }),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/held-session-9/take-over`,
        () => {
          tookOver.push("held-session-9");
          return HttpResponse.json(buildSession());
        },
      ),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/held-session-9/cancel`,
        () => {
          cancelled.push("held-session-9");
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Take over Anna Kowalska's session and continue",
      }),
    );

    await waitFor(() => expect(tookOver).toEqual(["held-session-9"]));
    expect(await screen.findByText("Widget — 5 pcs.")).toBeInTheDocument();
    expect(cancelled).toEqual([]);
    expect(starts).toBe(2);
  });

  it("keeps the session resumable when the sheet is closed", async () => {
    const cancelled: string[] = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/cancel`,
        ({ params }) => {
          cancelled.push(String(params.sessionId));
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledWith());
    // Closing the sheet is not a decision to put anything back: the scans
    // already recorded stay counted server-side, and the next start hands
    // this session back — the resume the browser's back arrow always had.
    expect(cancelled).toEqual([]);
  });

  it("keeps the session resumable when the sheet is left with Escape", async () => {
    const cancelled: string[] = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/cancel`,
        ({ params }) => {
          cancelled.push(String(params.sessionId));
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(onClose).toHaveBeenCalledWith());
    expect(cancelled).toEqual([]);
  });

  it("keeps the sheet open and says so when the cancel is refused", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/cancel`,
        () => HttpResponse.json({ detail: "Boom" }, { status: 500 }),
      ),
    );
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );

    // The session is still active server-side: the sheet stays, with the
    // sentence that explains why, instead of closing over the refusal.
    expect(
      await screen.findByText("Failed to cancel the picking session."),
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Widget — 5 pcs.")).toBeInTheDocument();
  });

  it("closes the sheet once the cancel goes through", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/cancel`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const onClose = vi.fn();

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalledWith());
  });

  it("says the work is kept when the sheet is closed", async () => {
    vi.mocked(toast).mockClear();
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));
    const onClose = vi.fn();

    const { unmount } = render(
      <WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />,
    );
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledWith());
    // The host drops the view once it is told to close.
    unmount();

    expect(toast).toHaveBeenCalledWith(
      "Paused — everything scanned so far is kept. Anyone can continue it, or complete the document with what was scanned.",
    );
  });

  it("says the work is kept when the screen goes away with the session open", async () => {
    vi.mocked(toast).mockClear();
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    const { unmount } = render(
      <WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />,
    );
    await screen.findByText("Widget — 5 pcs.");

    // The browser's back arrow: the route changes and the view is dropped
    // without the sheet's own close control being touched.
    unmount();

    expect(toast).toHaveBeenCalledWith(
      "Paused — everything scanned so far is kept. Anyone can continue it, or complete the document with what was scanned.",
    );
  });

  it("does not say the work is kept when the scans were discarded", async () => {
    vi.mocked(toast).mockClear();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/cancel`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const onClose = vi.fn();

    const { unmount } = render(
      <WmsPickingView documentId={DOCUMENT_ID} onClose={onClose} />,
    );
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledWith());
    unmount();

    expect(toast).not.toHaveBeenCalledWith(
      "Paused — everything scanned so far is kept. Anyone can continue it, or complete the document with what was scanned.",
    );
  });

  /** The line already off the shelf, so its row offers Undo. */
  function pickedSession(): WmsPickSession {
    const session = buildSession();
    session.picked_lines = 1;
    session.pending_lines = 0;
    session.lines[0] = {
      ...session.lines[0],
      status: "picked",
      picked_quantity: 3,
    };
    return session;
  }

  it("says the line was undone only when the server took it back", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(pickedSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/undo`,
        () =>
          HttpResponse.json(
            {
              detail: {
                code: "WMS_UNDO_LINE_IS_PACKED",
                message:
                  "Widget: a package already holds 3 of what was picked. Take it out of the package first, then undo the pick.",
              },
            },
            { status: 400 },
          ),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByRole("button", { name: "Undo" });

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));

    // The refusal and the white toast used to arrive together; the sheet
    // shows the server's sentence and the line stays counted.
    expect(
      await screen.findByText(/a package already holds 3 of what was picked/),
    ).toBeInTheDocument();
    expect(toast).not.toHaveBeenCalledWith("Undone: Widget");
    expect(screen.getByText("3/5 pcs.")).toBeInTheDocument();
  });

  it("announces an undo the server carried out", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(pickedSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/undo`,
        () =>
          HttpResponse.json({
            line_id: "pick-line-1",
            product_name: "Widget",
            restored_quantity: 0,
          }),
      ),
    );

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByRole("button", { name: "Undo" });

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));

    await waitFor(() => expect(toast).toHaveBeenCalledWith("Undone: Widget"));
  });

  it("leads a phone with the shelf: the code large, the name under it", async () => {
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
    const atTheShelf = buildSession();
    atTheShelf.lines[0].location_id = "loc-a";
    atTheShelf.lines[0].location_code = "A-02-01";
    atTheShelf.lines[0].location_name = "Aisle A, shelf 2";
    atTheShelf.shelf_scan_required = true;
    server.use(http.post(START_PATH, () => HttpResponse.json(atTheShelf)));

    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    const code = await screen.findByText("A-02-01");
    expect(code).toHaveClass("text-xl");
    expect(screen.getByText("Take from")).toBeInTheDocument();
    expect(screen.getByText("Aisle A, shelf 2")).toBeInTheDocument();
    // The session asks for the label before the product. The line's own row
    // says it too, so the assertion stays inside the card.
    const card = screen.getByText("Take from").parentElement as HTMLElement;
    expect(
      within(card).getByText("Scan the location label"),
    ).toBeInTheDocument();
    // The card replaced the small "Go to" line on a phone.
    expect(screen.queryByText("Go to A-01-02")).toBeNull();

    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });
});

describe("a scan the dispatch does not take", () => {
  function serveAnswer(answer: Record<string, unknown>) {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/picking/:sessionId/scan`,
        () =>
          HttpResponse.json({
            line_id: null,
            picked_quantity: 0,
            expected_quantity: 0,
            uom_symbol: null,
            bin_location: null,
            lot_name: null,
            planned_lot_name: null,
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

  it("names the product that is not on the dispatch beside the field, and buzzes", async () => {
    serveAnswer({
      status: "not_in_document",
      product_name: "APC Smart-UPS 3000VA",
    });
    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    const field = await screen.findByPlaceholderText("Scan barcode or type…");

    scanIntoField("7000000000001", field as HTMLInputElement);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "APC Smart-UPS 3000VA is not on this dispatch",
    );
    expect(toast.error).not.toHaveBeenCalled();
    expect(navigator.vibrate).toHaveBeenCalledWith([80, 60, 80]);
  });

  it("says how much of an already picked line was taken", async () => {
    serveAnswer({
      status: "already_picked",
      product_name: "ThinkPad T14s",
      picked_quantity: 2,
      expected_quantity: 2,
      uom_symbol: "pcs",
    });
    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    const field = await screen.findByPlaceholderText("Scan barcode or type…");

    scanIntoField("7000000000002", field as HTMLInputElement);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ThinkPad T14s already picked: 2 of 2 pcs.",
    );
    expect(navigator.vibrate).toHaveBeenCalledWith([80, 60, 80]);
  });

  it("says a skipped line was skipped, not that nothing of it was picked", async () => {
    serveAnswer({
      status: "line_skipped",
      product_name: "ThinkPad T14s",
      picked_quantity: 0,
      expected_quantity: 2,
      uom_symbol: "pcs",
    });
    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    const field = await screen.findByPlaceholderText("Scan barcode or type…");

    scanIntoField("7000000000002", field as HTMLInputElement);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "ThinkPad T14s was skipped — undo the skip to pick it",
    );
    expect(alert).not.toHaveTextContent("already picked");
  });

  it("keeps a code that matches no product as its own toast, without the refusal", async () => {
    serveAnswer({ status: "not_found" });
    render(<WmsPickingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    const field = await screen.findByPlaceholderText("Scan barcode or type…");

    scanIntoField("0000000000000", field as HTMLInputElement);

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error).mock.calls[0][0]).toBe(
      "No product has the code 0000000000000",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
