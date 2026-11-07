import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { act, render, screen, waitFor, within } from "@/test/utils";
import { render as rtlRender } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n/config";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import { toast } from "sonner";
import {
  insertScanIntoField,
  pauseBeforeScan,
  scanIntoField,
  scanWithHardwareScanner,
} from "@/test/scanner";
import WmsReceivingView from "./WmsReceivingView";
import type { WmsReceiveSession } from "@/modules/warehouse/api/documents_receiving";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
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
const START_PATH = `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/start`;

function buildSession(): WmsReceiveSession {
  return {
    id: "session-1",
    document_id: DOCUMENT_ID,
    assigned_to: null,
    status: "active",
    started_at: "2026-04-05T08:00:00Z",
    completed_at: null,
    total_lines: 1,
    received_lines: 0,
    pending_lines: 1,
    shelf_scan_required: false,
    lines: [
      {
        id: "receive-line-1",
        document_line_id: "line-1",
        from_order: false,
        expected_is_count: false,
        pick_order: 1,
        status: "pending",
        received_quantity: 0,
        product_name: "Widget",
        lot_name: null,
        expected_quantity: 5,
        uom_symbol: "pcs",
      },
    ],
  };
}

/** The same session, with the row's line already aimed somewhere. */
function sessionPlannedAt(
  locationName: string,
  source: string,
): WmsReceiveSession {
  const session = buildSession();
  return {
    ...session,
    lines: [
      {
        ...session.lines[0],
        planned_location_id: `loc-${locationName}`,
        planned_location_name: locationName,
        planned_source: source,
      },
    ],
  };
}

describe("WmsReceivingView", () => {
  it.each([
    ["rejected", "This document was completed or cancelled.", true],
    ["all_received", "All lines have already been received.", false],
  ])("announces the %s scan response", async (status, message, rejected) => {
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast).mockClear();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        () => HttpResponse.json({ status, session_complete: false }),
      ),
    );
    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    invalidate.mockClear();
    await userEvent.type(
      screen.getByPlaceholderText("Scan product barcode…"),
      "1234567890123{enter}",
    );
    await waitFor(() =>
      expect(rejected ? toast.error : toast).toHaveBeenCalledWith(message),
    );
    if (rejected) expect(invalidate).toHaveBeenCalled();
    invalidate.mockRestore();
  });
  it("says the shelves could not be loaded instead of offering none", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.get(
        "/api/v1/locations",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("starts the session on mount and shows the line to receive", async () => {
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    expect(await screen.findByText("Widget — 5 pcs.")).toBeInTheDocument();
    expect(screen.getByText("Receive stock")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Scan product barcode…"),
    ).toBeInTheDocument();
  });

  it("closes with a 44 px target, not the compact 32 px one", async () => {
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    const close = screen.getByRole("button", { name: "Close" });
    expect(close).toHaveClass("h-11", "w-11");
    expect(close).not.toHaveClass("h-8");
  });

  it("leaves nothing where the unit would stand on a line that has none", async () => {
    // A hand-written line carries no unit, and the sentence above the scan
    // field has a slot for one: it used to fill it with a dash, so the
    // number read as a quantity measured in "—".
    const session = buildSession();
    session.lines = [{ ...session.lines[0], uom_symbol: null }];
    server.use(http.post(START_PATH, () => HttpResponse.json(session)));

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    expect(await screen.findByText("Widget — 5")).toBeInTheDocument();
    expect(screen.queryByText(/Widget — 5 —/)).toBeNull();
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
      <WmsReceivingView
        documentId={DOCUMENT_ID}
        onClose={vi.fn()}
        onRequestApproval={onRequestApproval}
      />,
    );

    expect(
      await screen.findByText(
        "This document requires approval before receiving can start. Requesting it moves the document back to awaiting approval, where it stays until someone signs off.",
      ),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Request approval" }),
    );
    expect(onRequestApproval).toHaveBeenCalledTimes(1);
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

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    // Not "Boom": a 5xx detail is written for the logs and no longer reaches
    // the reader. A 4xx reason — "a receiving session is already open" — still
    // does, and that is the one this screen was built to surface.
    //
    // And not an English literal either. It used to be one, sitting in the
    // hook as the fallback argument, so a Polish reader met "Failed to start
    // receiving" over Polish buttons. The words come from the namespace now.
    expect(
      await screen.findByText("Failed to start the receiving session."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Request approval" }),
    ).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(starts).toBe(2));
  });

  it("names the holder of a held document and can release their session", async () => {
    // The resume change left one hole: a colleague meeting the refusal had
    // no way in — the document waited for its holder to come back. The
    // refusal now names the holder and carries the session id, and the
    // dialog's release action goes through the release door, then starts
    // the reader's own session.
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
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/held-session-9/release`,
        () => {
          cancelled.push("held-session-9");
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

    // The refusal names the holder and says what a release costs.
    expect(
      await screen.findByText(/Anna Kowalska has an active receiving session/),
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
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/held-session-9/take-over`,
        () => {
          tookOver.push("held-session-9");
          return HttpResponse.json(buildSession());
        },
      ),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/held-session-9/cancel`,
        () => {
          cancelled.push("held-session-9");
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);

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

  it("pauses the session, keeping its scans, when the sheet is closed", async () => {
    const cancelled: string[] = [];
    const paused: string[] = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/pause`,
        ({ params }) => {
          paused.push(String(params.sessionId));
          return new HttpResponse(null, { status: 204 });
        },
      ),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/cancel`,
        ({ params }) => {
          cancelled.push(String(params.sessionId));
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );
    const onClose = vi.fn();

    vi.mocked(toast).mockClear();
    const { unmount } = render(
      <WmsReceivingView documentId={DOCUMENT_ID} onClose={onClose} />,
    );
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledWith());
    // The host drops the view once it is told to close.
    unmount();
    expect(toast).toHaveBeenCalledWith(
      "Paused — everything scanned so far is kept. Anyone can continue it, or complete the document with what was scanned.",
    );
    // Closing the sheet is not a decision to put anything back: what was
    // received stays on the session, and the next start hands it back —
    // the resume the browser's back arrow always had. It is paused, so it
    // no longer holds the document for anyone else.
    expect(cancelled).toEqual([]);
    await waitFor(() => expect(paused).toEqual([buildSession().id]));
  });

  it("asks the receiver to wait when the scans come faster than the API takes them", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        () =>
          HttpResponse.json(
            { detail: "Too many requests. Try again later." },
            { status: 429 },
          ),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    (document.activeElement as HTMLElement | null)?.blur();
    scanWithHardwareScanner("1234567890123", document.body);

    expect(
      await screen.findByText(
        "Too many scans in a minute. Wait a moment, then scan again.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Too many requests. Try again later."),
    ).not.toBeInTheDocument();
  });

  it("records a receipt from a hardware scanner while the focus is off the field", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "received",
            line_id: "receive-line-1",
            product_name: "Widget",
            received_quantity: 1,
            expected_quantity: 5,
            uom_symbol: "pcs",
            session_complete: false,
          });
        },
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    expect(
      screen.getByText("A barcode scanner can be used on this screen"),
    ).toBeInTheDocument();

    (document.activeElement as HTMLElement | null)?.blur();
    scanWithHardwareScanner("1234567890123", document.body);

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ barcode: "1234567890123", quantity: 1 });
    expect(toast.success).toHaveBeenCalled();
  });

  it.each([
    ["a keyboard-wedge burst", scanIntoField],
    ["a scanning keyboard's single insertion", insertScanIntoField],
  ])(
    "takes a receipt with the quantity typed before it from %s",
    async (_name, scanInto) => {
      const bodies: Array<Record<string, unknown>> = [];
      server.use(
        http.post(START_PATH, () => HttpResponse.json(buildSession())),
        http.post(
          `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
          async ({ request }) => {
            bodies.push((await request.json()) as Record<string, unknown>);
            return HttpResponse.json({
              status: "received",
              line_id: "receive-line-1",
              product_name: "Widget",
              received_quantity: 20,
              expected_quantity: 5,
              uom_symbol: "pcs",
              session_complete: false,
            });
          },
        ),
      );

      render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
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

  it("confirms a zone from its one-letter shelf code, scanned into the field with Tab or into the quantity", async () => {
    // A business warehouse's template gives a zone the code "A".
    const bodies: Array<Record<string, unknown>> = [];
    const session = sessionPlannedAt("Zone A", "document");
    session.shelf_scan_required = true;
    server.use(
      http.post(START_PATH, () => HttpResponse.json(session)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "shelf_confirmed",
            shelf: "A · Zone A",
            shelf_id: "zone-a",
            message: "",
          });
        },
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    const field = screen.getByPlaceholderText("Scan product barcode…");
    // A one-letter code is a scan only at a scanner's own pace, every key
    // under 30 ms: typed by the test at whatever speed the host allows, it
    // used to arrive as two separate keys and confirm nothing.
    scanIntoField("A", field as HTMLInputElement, "Tab");
    await waitFor(() => expect(bodies).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 350));

    const quantity = screen.getByRole("spinbutton", { name: "Quantity" });
    scanIntoField("A", quantity as HTMLInputElement);
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies.map((body) => body.barcode)).toEqual(["A", "A"]);
  });

  it("keeps a quantity typed by hand, digit by digit, and does not scan it", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "received",
            line_id: "receive-line-1",
            product_name: "Widget",
            received_quantity: 20,
            expected_quantity: 5,
            uom_symbol: "pcs",
            session_complete: false,
          });
        },
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
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
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({
            status: "received",
            line_id: "receive-line-1",
            product_name: "Widget",
            received_quantity: 1,
            expected_quantity: 5,
            uom_symbol: "pcs",
            session_complete: false,
          });
        },
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
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
    // The receipt is recorded exactly as the same code typed and confirmed.
    expect(await screen.findByText("Widget — 1/5 pcs.")).toBeInTheDocument();
  });

  it("says why the empty Scan cannot open a camera instead of doing nothing", async () => {
    cameraMock.scannerError =
      "No camera was found on this device. Connect a camera or use a different device.";
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({ status: "not_found", message: "" });
        },
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
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

  it("refreshes the document as the summary appears", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const onClose = vi.fn();

    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        () =>
          HttpResponse.json({
            status: "received",
            line_id: "receive-line-1",
            product_name: "Widget",
            received_quantity: 5,
            expected_quantity: 5,
            uom_symbol: "pcs",
            session_complete: true,
          }),
      ),
    );

    rtlRender(<WmsReceivingView documentId={DOCUMENT_ID} onClose={onClose} />, {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
        </QueryClientProvider>
      ),
    });
    await screen.findByText("Widget — 5 pcs.");

    const barcodeInput = screen.getByPlaceholderText("Scan product barcode…");
    await userEvent.type(barcodeInput, "1234567890123");
    await userEvent.click(screen.getByRole("button", { name: "Scan" }));

    expect(await screen.findByText("Receiving complete")).toBeInTheDocument();

    // The refresh happens as the summary appears, not when it is dismissed:
    // the summary said "received" over a document still reading "Done 0".
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: ["documents", DOCUMENT_ID] }),
      );
    });

    await userEvent.click(
      screen.getByRole("button", { name: "Complete and post stock" }),
    );
    expect(onClose).toHaveBeenCalledWith(true);
  });

  it("books nothing at the last scan: the summary comes first and its closing completes the document", async () => {
    // Stock is booked by the document's completion. It used to fire the
    // moment the last scan resolved the session, with no screen to look at
    // in between; picking has always shown its summary first.
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        () =>
          HttpResponse.json({
            status: "received",
            line_id: "receive-line-1",
            product_name: "Widget",
            received_quantity: 5,
            expected_quantity: 5,
            uom_symbol: "pcs",
            session_complete: true,
          }),
      ),
    );
    const onClose = vi.fn();

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.type(
      screen.getByPlaceholderText("Scan product barcode…"),
      "1234567890123",
    );
    await userEvent.click(screen.getByRole("button", { name: "Scan" }));

    expect(await screen.findByText("Receiving complete")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Closing this summary completes the document and books the stock.",
      ),
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("button", { name: "Complete and post stock" }),
    );
    expect(onClose).toHaveBeenCalledExactlyOnceWith(true);
  });

  it("reopens on the summary of a session that finished without completing the document", async () => {
    // The summary was left by the back arrow or a closed tab; the start
    // hands that session back instead of a fresh one at 0 of N.
    const finished = buildSession();
    finished.status = "completed";
    finished.received_lines = 1;
    finished.pending_lines = 0;
    finished.lines = [
      { ...finished.lines[0], status: "received", received_quantity: 5 },
    ];
    server.use(http.post(START_PATH, () => HttpResponse.json(finished)));
    const onClose = vi.fn();

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={onClose} />);

    expect(await screen.findByText("Receiving complete")).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Scan product barcode…"),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Complete and post stock" }),
    );
    expect(onClose).toHaveBeenCalledExactlyOnceWith(true);
  });

  it("asks before skipping a line and sends nothing when declined", async () => {
    const skipped = vi.fn();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/skip`,
        () => {
          skipped();
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(screen.getByRole("button", { name: "Skip line" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(skipped).not.toHaveBeenCalled();
  });

  it("reports a full-quantity short-receive with the received toast", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/short-receive`,
        () =>
          HttpResponse.json({
            status: "short_receive_confirmed",
            line_id: "receive-line-1",
            product_name: "Widget",
            received_quantity: 5,
            expected_quantity: 5,
            uom_symbol: "pcs",
            message: "Short receive: 5/5",
            session_complete: true,
          }),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(
      screen.getByRole("button", { name: "Record received quantity" }),
    );
    // Typing the expected quantity into the dialog is a full receive.
    await userEvent.type(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
      "5",
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Widget: 5 pcs. received"),
    );
    expect(toast).not.toHaveBeenCalledWith("Short receive confirmed");
  });

  it("receives the whole line from the row's own named action", async () => {
    let receivedBody: Record<string, unknown> | null = null;
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/short-receive`,
        async ({ request }) => {
          receivedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({
            status: "short_receive_confirmed",
            line_id: "receive-line-1",
            product_name: "Widget",
            received_quantity: 5,
            expected_quantity: 5,
            uom_symbol: "pcs",
            message: "Short receive: 5/5",
            session_complete: true,
          });
        },
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    // One tap, with no window in between: the row offers the whole line by
    // name, and the number it sends is the document's own expectation.
    await userEvent.click(
      screen.getByRole("button", { name: "Receive full amount" }),
    );

    await waitFor(() => expect(receivedBody).not.toBeNull());
    expect(receivedBody).toMatchObject({
      line_id: "receive-line-1",
      received_quantity: 5,
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Widget: 5 pcs. received"),
    );
  });

  it("keeps the line open and names the location when the full amount is refused for want of a scan", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/short-receive`,
        () =>
          HttpResponse.json({
            status: "shelf_required",
            line_id: "receive-line-1",
            shelf: "A-01 · Rack A",
            shelf_id: "shelf-a",
            received_quantity: 0,
            expected_quantity: 5,
            message: "Scan the location first: A-01 · Rack A",
            session_complete: false,
          }),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    await userEvent.click(
      screen.getByRole("button", { name: "Receive full amount" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Scan the location first: A-01 · Rack A",
      ),
    );
    expect(toast.success).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Receive full amount" }),
    ).toBeInTheDocument();
  });

  it("takes the confirmation back when another location's label is scanned", async () => {
    const session = sessionPlannedAt("Rack A", "document");
    session.shelf_scan_required = true;
    session.lines[0].planned_location_id = "shelf-a";
    session.lines[0].planned_location_code = "A-01";
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
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        () => HttpResponse.json(answers.shift()),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");
    const field = screen.getByPlaceholderText("Scan product barcode…");
    await userEvent.type(field, "SHF-A1");
    await userEvent.click(screen.getByRole("button", { name: "Scan" }));
    expect(await screen.findByText("Location confirmed")).toBeInTheDocument();

    await userEvent.type(field, "SHF-B2");
    await userEvent.click(screen.getByRole("button", { name: "Scan" }));
    expect(
      await screen.findByText("Scan the location to confirm"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Location confirmed")).not.toBeInTheDocument();
  });

  it.each([
    [null, false],
    ["A-01", true],
  ])(
    "hints at the shelf label when the planned shelf's code is %s: %s",
    async (code, hinted) => {
      // The session asks for a label only where there is something to scan;
      // a hint on a codeless shelf promised a label that does not exist.
      const session = sessionPlannedAt("Rack A", "document");
      session.shelf_scan_required = true;
      session.lines[0].planned_location_id = "shelf-a";
      session.lines[0].planned_location_code = code;
      server.use(http.post(START_PATH, () => HttpResponse.json(session)));

      render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
      await screen.findByText("Widget — 5 pcs.");

      expect(screen.queryByText("Scan the location to confirm") !== null).toBe(
        hinted,
      );
    },
  );

  it("says where to give the product the code a scan did not find", async () => {
    // A code nothing carries is a dead end at the terminal unless the
    // session names the code and the place a worker gives it to a product.
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        () =>
          HttpResponse.json({
            status: "not_found",
            message: "Product not recognized",
          }),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.type(
      screen.getByPlaceholderText("Scan product barcode…"),
      "5901234123457",
    );
    await userEvent.click(screen.getByRole("button", { name: "Scan" }));

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

  it("speaks the namespace's sentence when the scan cannot be recorded", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`,
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.type(
      screen.getByPlaceholderText("Scan product barcode…"),
      "1234567890123",
    );
    await userEvent.click(screen.getByRole("button", { name: "Scan" }));

    // The hook no longer carries a fallback sentence of its own, so the
    // words come from the namespace — not "Scan failed" over Polish buttons.
    expect(
      await screen.findByText("Failed to record the scan."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Scan failed")).not.toBeInTheDocument();
  });

  it("shows no success toast when the server rejects the quantity", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/short-receive`,
        () =>
          HttpResponse.json(
            {
              detail: {
                code: "VALIDATION_ERROR",
                message: "Session is closed",
              },
            },
            { status: 400 },
          ),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(
      screen.getByRole("button", { name: "Record received quantity" }),
    );
    await userEvent.type(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
      "5",
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Session is closed",
    );
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalledWith("Short receive confirmed");
  });

  it("names a shelf from the floor row and shows the plan that comes back", async () => {
    // The whole wiring in one test, because each half passes on its own
    // while the screen stays wrong: the row reports the choice, the hook
    // can re-read the session, and between them sat a missing call — which
    // is the defect this screen was written with. Take the refresh out of
    // the view and this is the only test that notices.
    const patched: (string | null)[] = [];
    serveLocations([
      { id: "loc-Shelf A", name: "Shelf A" },
      { id: "loc-2", name: "Cold Room" },
    ]);
    server.use(
      http.post(START_PATH, () =>
        HttpResponse.json(sessionPlannedAt("Shelf A", "rule")),
      ),
      http.patch(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/lines/line-1`,
        async ({ request }) => {
          const body = (await request.json()) as {
            target_location_id: string | null;
          };
          patched.push(body.target_location_id);
          return HttpResponse.json({ id: DOCUMENT_ID, lines: [] });
        },
      ),
      http.get(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/session-1`,
        () => HttpResponse.json(sessionPlannedAt("Cold Room", "line")),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    expect(await screen.findByText("→ Shelf A")).toBeInTheDocument();

    await userEvent.click(
      await screen.findByRole("combobox", { name: "Line location" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /Cold Room/ }),
    );

    await waitFor(() => expect(patched).toEqual(["loc-2"]));
    expect(await screen.findByText("→ Cold Room")).toBeInTheDocument();
  });

  it("keeps the sheet open and says so when the cancel is refused", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/cancel`,
        () => HttpResponse.json({ detail: "Boom" }, { status: 500 }),
      ),
    );
    const onClose = vi.fn();

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );

    // The session is still active server-side: the sheet stays, with the
    // sentence that explains why, instead of closing over the refusal.
    expect(
      await screen.findByText("Failed to cancel the receiving session."),
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("Widget — 5 pcs.")).toBeInTheDocument();
  });

  it("asks before discarding a session in which something is already received", async () => {
    const started = buildSession();
    started.lines[0].received_quantity = 2;
    const cancelled = vi.fn();
    server.use(
      http.post(START_PATH, () => HttpResponse.json(started)),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/cancel`,
        () => {
          cancelled();
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );
    const onClose = vi.fn();

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Discard scans" }),
    );

    const dialog = await screen.findByRole("alertdialog");
    expect(cancelled).not.toHaveBeenCalled();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Discard scans" }),
    );
    await waitFor(() => expect(cancelled).toHaveBeenCalledOnce());
    await waitFor(() => expect(onClose).toHaveBeenCalledWith());
  });

  it("closes the sheet once the cancel goes through", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/cancel`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const onClose = vi.fn();

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={onClose} />);
    await screen.findByText("Widget — 5 pcs.");

    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalledWith());
  });

  it("says the work is kept when the screen goes away with the session open", async () => {
    vi.mocked(toast).mockClear();
    server.use(http.post(START_PATH, () => HttpResponse.json(buildSession())));

    const { unmount } = render(
      <WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />,
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
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/cancel`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const onClose = vi.fn();

    const { unmount } = render(
      <WmsReceivingView documentId={DOCUMENT_ID} onClose={onClose} />,
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

  /** The line already off the truck, so its row offers Undo. */
  function receivedSession(): WmsReceiveSession {
    const session = buildSession();
    session.received_lines = 1;
    session.pending_lines = 0;
    session.lines[0] = {
      ...session.lines[0],
      status: "received",
      received_quantity: 3,
    };
    return session;
  }

  it("says the line was undone only when the server took it back", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(receivedSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/undo`,
        () =>
          HttpResponse.json(
            {
              detail: {
                code: "VALIDATION_ERROR",
                message: "Session is closed",
              },
            },
            { status: 400 },
          ),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByRole("button", { name: "Undo" });

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));

    // The refusal and the white toast used to arrive together; the sheet
    // shows the server's sentence and the line stays counted.
    expect(await screen.findByText("Session is closed")).toBeInTheDocument();
    expect(toast).not.toHaveBeenCalledWith("Reverted Widget");
    expect(screen.getByText("3/5 pcs.")).toBeInTheDocument();
  });

  it("announces an undo the server carried out", async () => {
    server.use(
      http.post(START_PATH, () => HttpResponse.json(receivedSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/undo`,
        () =>
          HttpResponse.json({
            line_id: "receive-line-1",
            product_name: "Widget",
            restored_quantity: 0,
          }),
      ),
    );

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByRole("button", { name: "Undo" });

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));

    await waitFor(() => expect(toast).toHaveBeenCalledWith("Reverted Widget"));
  });

  it("names the reason beside the quarantined amount the moment it is recorded, and drops both on Undo", async () => {
    // The row learned the amount from the response but kept the reason of
    // the previous read: "2 pcs. in quarantine —" until the screen was
    // reopened, and the line still said so after Undo took it back.
    server.use(
      http.post(START_PATH, () => HttpResponse.json(buildSession())),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/short-receive`,
        () =>
          HttpResponse.json({
            status: "short_receive_confirmed",
            line_id: "receive-line-1",
            product_name: "Widget",
            received_quantity: 5,
            expected_quantity: 5,
            uom_symbol: "pcs",
            message: "",
            session_complete: false,
          }),
      ),
      http.post(
        `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/undo`,
        () =>
          HttpResponse.json({
            line_id: "receive-line-1",
            product_name: "Widget",
            restored_quantity: 0,
          }),
      ),
    );
    const user = userEvent.setup();

    render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
    await screen.findByText("Widget — 5 pcs.");

    await user.click(
      screen.getByRole("button", { name: "Record received quantity" }),
    );
    await user.type(
      screen.getByRole("spinbutton", { name: "Final received quantity" }),
      "5",
    );
    const held = screen.getByRole("spinbutton", {
      name: "Quarantined (damaged or quality hold)",
    });
    await user.clear(held);
    await user.type(held, "2");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(
      await screen.findByText("2 pcs. in quarantine — Damage"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Undo" }));

    await waitFor(() =>
      expect(screen.queryByText(/in quarantine/)).not.toBeInTheDocument(),
    );
  });

  describe("a product that is received by earliest expiry", () => {
    const SCAN_PATH = `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/scan`;

    function serverAskingOnTheFirstScan(bodies: Record<string, unknown>[]) {
      server.use(
        http.post(START_PATH, () => HttpResponse.json(buildSession())),
        http.post(SCAN_PATH, async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          bodies.push(body);
          if (!body.expiry_date) {
            return HttpResponse.json({
              status: "needs_lot_expiry",
              line_id: "receive-line-1",
              product_name: "Widget",
              message: "Lot and expiry are needed for this product",
            });
          }
          return HttpResponse.json({
            status: "received",
            line_id: "receive-line-1",
            product_name: "Widget",
            received_quantity: 1,
            expected_quantity: 5,
            uom_symbol: "pcs",
            session_complete: false,
            message: "",
          });
        }),
      );
    }

    async function scanTheCode() {
      render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
      await screen.findByText("Widget — 5 pcs.");
      await userEvent.type(
        screen.getByPlaceholderText("Scan product barcode…"),
        "5901234123457",
      );
      await userEvent.click(screen.getByRole("button", { name: "Scan" }));
    }

    it("asks for the lot and the date, and sends the same scan again with them", async () => {
      const bodies: Record<string, unknown>[] = [];
      serverAskingOnTheFirstScan(bodies);

      await scanTheCode();

      const dialog = await screen.findByRole("dialog", {
        name: "Lot and expiry",
      });
      await userEvent.type(within(dialog).getByLabelText("Lot"), "LOT-A1");
      await userEvent.click(within(dialog).getByRole("combobox"));
      await userEvent.click(screen.getAllByTestId("date-preset")[1]);
      await userEvent.click(
        within(dialog).getByRole("button", { name: "Receive" }),
      );

      await waitFor(() => expect(toast.success).toHaveBeenCalled());
      expect(bodies).toHaveLength(2);
      expect(bodies[0]).not.toHaveProperty("expiry_date");
      expect(bodies[1]).toMatchObject({
        barcode: "5901234123457",
        batch_number: "LOT-A1",
        expiry_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      });
      expect(
        screen.queryByRole("dialog", { name: "Lot and expiry" }),
      ).not.toBeInTheDocument();
    });

    it("will not send the scan again without a date", async () => {
      const bodies: Record<string, unknown>[] = [];
      serverAskingOnTheFirstScan(bodies);

      await scanTheCode();

      const dialog = await screen.findByRole("dialog", {
        name: "Lot and expiry",
      });
      await userEvent.click(
        within(dialog).getByRole("button", { name: "Receive" }),
      );

      expect(
        await within(dialog).findByText("Enter the expiry date from the pack"),
      ).toBeInTheDocument();
      expect(bodies).toHaveLength(1);
    });

    it("asks on 'Receive full amount' too, and sends the same call again with the date", async () => {
      const bodies: Record<string, unknown>[] = [];
      server.use(
        http.post(START_PATH, () => HttpResponse.json(buildSession())),
        http.post(
          `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/short-receive`,
          async ({ request }) => {
            const body = (await request.json()) as Record<string, unknown>;
            bodies.push(body);
            if (!body.expiry_date) {
              return HttpResponse.json({
                status: "needs_lot_expiry",
                line_id: "receive-line-1",
                product_name: "Widget",
                message: "Lot and expiry are needed for this product",
              });
            }
            return HttpResponse.json({
              status: "short_receive_confirmed",
              line_id: "receive-line-1",
              product_name: "Widget",
              received_quantity: 5,
              expected_quantity: 5,
              uom_symbol: "pcs",
              session_complete: false,
              message: "",
            });
          },
        ),
      );
      render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
      await screen.findByText("Widget — 5 pcs.");

      await userEvent.click(
        screen.getByRole("button", { name: "Receive full amount" }),
      );

      const dialog = await screen.findByRole("dialog", {
        name: "Lot and expiry",
      });
      expect(toast.success).not.toHaveBeenCalled();
      await userEvent.click(within(dialog).getByRole("combobox"));
      await userEvent.click(screen.getAllByTestId("date-preset")[1]);
      await userEvent.click(
        within(dialog).getByRole("button", { name: "Receive" }),
      );

      await waitFor(() => expect(toast.success).toHaveBeenCalled());
      expect(bodies).toHaveLength(2);
      expect(bodies[0]).not.toHaveProperty("expiry_date");
      expect(bodies[1]).toMatchObject({
        line_id: "receive-line-1",
        received_quantity: 5,
        expiry_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      });
    });

    it("puts the expiry question in front of the short-receive sheet, and Cancel returns to the sheet", async () => {
      const bodies: Record<string, unknown>[] = [];
      server.use(
        http.post(START_PATH, () => HttpResponse.json(buildSession())),
        http.post(
          `/api/v1/warehouse/documents/${DOCUMENT_ID}/receiving/:sessionId/short-receive`,
          async ({ request }) => {
            const body = (await request.json()) as Record<string, unknown>;
            bodies.push(body);
            if (!body.expiry_date) {
              return HttpResponse.json({
                status: "needs_lot_expiry",
                line_id: "receive-line-1",
                product_name: "Widget",
                message: "Lot and expiry are needed for this product",
              });
            }
            return HttpResponse.json({
              status: "short_receive_confirmed",
              line_id: "receive-line-1",
              product_name: "Widget",
              received_quantity: 3,
              expected_quantity: 5,
              uom_symbol: "pcs",
              session_complete: false,
              message: "",
            });
          },
        ),
      );
      render(<WmsReceivingView documentId={DOCUMENT_ID} onClose={vi.fn()} />);
      await screen.findByText("Widget — 5 pcs.");

      await userEvent.click(
        screen.getByRole("button", { name: "Record received quantity" }),
      );
      await userEvent.type(
        screen.getByRole("spinbutton", { name: "Final received quantity" }),
        "3",
      );
      await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

      // Both sheets share one layer, so the quantity sheet must not be
      // mounted over the question it just raised.
      const dialog = await screen.findByRole("dialog", {
        name: "Lot and expiry",
      });
      expect(
        screen.queryByRole("spinbutton", { name: "Final received quantity" }),
      ).not.toBeInTheDocument();

      // Cancelling the question gives the quantity sheet back, with the
      // count the worker had typed still in it.
      await userEvent.click(
        within(dialog).getByRole("button", { name: "Cancel" }),
      );
      expect(
        await screen.findByRole("spinbutton", {
          name: "Final received quantity",
        }),
      ).toHaveValue(3);
      expect(toast.success).not.toHaveBeenCalled();

      // Asked again, the date resends the quantity typed the first time.
      await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
      const again = await screen.findByRole("dialog", {
        name: "Lot and expiry",
      });
      await userEvent.click(within(again).getByRole("combobox"));
      await userEvent.click(screen.getAllByTestId("date-preset")[1]);
      await userEvent.click(
        within(again).getByRole("button", { name: "Receive" }),
      );

      await waitFor(() => expect(bodies).toHaveLength(3));
      expect(bodies.at(-1)).toMatchObject({
        line_id: "receive-line-1",
        received_quantity: 3,
        expiry_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      });
    });
  });
});
