import { QueryWrapper } from "@/test/queryWrapper";
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { useWmsReceiving } from "../useWmsReceiving";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

beforeEach(() => {
  server.resetHandlers();
});

const mockLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  pick_order: 1,
  status: "pending",
  received_quantity: 0,
  product_name: "Rice 5kg",
  lot_name: null,
  expected_quantity: 10,
  uom_symbol: "kg",
};

const mockSession = {
  id: "session-1",
  document_id: "doc-1",
  assigned_to: null,
  status: "active",
  started_at: "2026-08-02T10:00:00Z",
  completed_at: null,
  lines: [mockLine],
  total_lines: 1,
  received_lines: 0,
  pending_lines: 1,
};

const DOC = "/api/v1/warehouse/documents/doc-1/receiving";

describe("useWmsReceiving", () => {
  it("starts a session and moves to active phase", async () => {
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(mockSession, { status: 201 }),
      ),
    );
    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    expect(result.current.state.phase).toBe("active");
    expect(result.current.state.session?.id).toBe("session-1");
    expect(result.current.pendingCount).toBe(1);
  });

  it("marks a line received on scan and completes when session_complete", async () => {
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(mockSession, { status: 201 }),
      ),
      http.post(`${DOC}/session-1/scan`, () =>
        HttpResponse.json({
          status: "received",
          line_id: "line-1",
          product_name: "Rice 5kg",
          received_quantity: 10,
          expected_quantity: 10,
          uom_symbol: "kg",
          message: "",
          session_complete: true,
        }),
      ),
    );
    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    await act(async () => {
      await result.current.scan("5909999123456", 10);
    });
    expect(result.current.state.lines[0].status).toBe("received");
    expect(result.current.state.phase).toBe("completed");
    expect(result.current.receivedCount).toBe(1);
  });

  it("confirms a short receive with a discrepancy code", async () => {
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(mockSession, { status: 201 }),
      ),
      http.post(`${DOC}/session-1/short-receive`, () =>
        HttpResponse.json({
          status: "short",
          line_id: "line-1",
          product_name: "Rice 5kg",
          received_quantity: 8,
          expected_quantity: 10,
          uom_symbol: "kg",
          message: "",
          session_complete: false,
        }),
      ),
    );
    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    await act(async () => {
      await result.current.confirmShortReceive("line-1", 8, "SHORTAGE");
    });
    expect(result.current.state.lines[0].status).toBe("short");
    expect(result.current.state.lines[0].received_quantity).toBe(8);
    expect(result.current.state.phase).toBe("active");
  });

  it("undoes a received line back to pending", async () => {
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(mockSession, { status: 201 }),
      ),
      http.post(`${DOC}/session-1/undo`, () =>
        HttpResponse.json({
          line_id: "line-1",
          product_name: "Rice 5kg",
          restored_quantity: 10,
        }),
      ),
    );
    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    await act(async () => {
      await result.current.undoLine("line-1");
    });
    expect(result.current.state.lines[0].status).toBe("pending");
  });

  it("skips a line and completes when all lines are resolved", async () => {
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(mockSession, { status: 201 }),
      ),
      http.post(`${DOC}/session-1/skip`, () =>
        HttpResponse.json({ status: "skipped", session_complete: false }),
      ),
    );
    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    await act(async () => {
      await result.current.skipLine("line-1");
    });
    expect(result.current.state.lines[0].status).toBe("skipped");
    expect(result.current.state.phase).toBe("completed");
  });

  it("cancels the session", async () => {
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(mockSession, { status: 201 }),
      ),
      http.post(`${DOC}/session-1/cancel`, () =>
        HttpResponse.json(null, { status: 204 }),
      ),
    );
    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    await act(async () => {
      await result.current.cancelSession();
    });
    expect(result.current.state.phase).toBe("cancelled");
  });

  it("reports scan errors without crashing", async () => {
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(mockSession, { status: 201 }),
      ),
      http.post(`${DOC}/session-1/scan`, () =>
        HttpResponse.json({ detail: "Barcode not found" }, { status: 404 }),
      ),
    );
    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    let scanResult: unknown = "unset";
    await act(async () => {
      scanResult = await result.current.scan("nope", 1);
    });
    expect(scanResult).toBeNull();
    expect(result.current.error).toBe("Barcode not found");
  });

  it("extracts the message from structured error details", async () => {
    // Backend errors use { detail: { code, message, lang } } — the hook must
    // store a plain string, or rendering {error} crashes React.
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(
          {
            detail: {
              code: "VALIDATION_ERROR",
              message:
                "An active receiving session already exists for this document",
              lang: "en",
            },
          },
          { status: 409 },
        ),
      ),
    );
    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    expect(result.current.error).toBe(
      "An active receiving session already exists for this document",
    );
  });

  it("exposes the error code so the view can map APPROVAL_REQUIRED", async () => {
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(
          {
            detail: {
              code: "APPROVAL_REQUIRED",
              message: "Operation requires approval before completion.",
              lang: "en",
            },
          },
          { status: 409 },
        ),
      ),
    );
    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    expect(result.current.errorCode).toBe("APPROVAL_REQUIRED");
    expect(result.current.state.phase).toBe("idle");
  });

  it("refreshPlans re-reads the session and keeps rows already resolved", async () => {
    // Named for what it pins — the hook's own call — because the screen's
    // half of this belongs to the view: whether anything ever calls it is
    // what WmsReceivingView.test.tsx answers, and the two failed apart.
    //
    // The planned shelf is computed from the document's lines, not stored on
    // the session's, so naming a shelf changes nothing this state machine
    // holds. Without this read the row keeps showing the old address.
    server.use(
      http.post(`${DOC}/start`, () =>
        HttpResponse.json(
          {
            ...mockSession,
            lines: [{ ...mockLine, planned_location_name: "Shelf A" }],
          },
          { status: 201 },
        ),
      ),
      http.post(`${DOC}/session-1/skip`, () => HttpResponse.json({})),
      http.get(`${DOC}/session-1`, () =>
        HttpResponse.json({
          ...mockSession,
          // The server has caught up with the choice, and still believes the
          // row is pending — it was resolved only in the local machine.
          lines: [
            {
              ...mockLine,
              status: "pending",
              planned_location_name: "Cold Room",
              planned_source: "line",
            },
          ],
        }),
      ),
    );

    const { result } = renderHook(() => useWmsReceiving("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await result.current.startSession();
    });
    expect(result.current.state.lines[0].planned_location_name).toBe("Shelf A");

    await act(async () => {
      await result.current.skipLine("line-1");
    });
    await act(async () => {
      await result.current.refreshPlans();
    });

    expect(result.current.state.lines[0].planned_location_name).toBe(
      "Cold Room",
    );
    // The local machine is ahead of the server for a row just resolved, so
    // the refresh must not hand the worker back a row they already dealt with.
    expect(result.current.state.lines[0].status).toBe("skipped");
  });
});
