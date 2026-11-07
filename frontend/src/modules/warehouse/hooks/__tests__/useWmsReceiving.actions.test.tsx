import { QueryWrapper } from "@/test/queryWrapper";
import { describe, expect, it, vi } from "vitest";
import { act, renderHook, type RenderHookResult } from "@testing-library/react";
import { useWmsReceiving } from "../useWmsReceiving";
import type {
  WmsReceiveLine,
  WmsReceiveSession,
} from "../../api/documents_receiving";

const startWmsReceivingMock = vi.hoisted(() => vi.fn());
const shortReceiveMock = vi.hoisted(() => vi.fn());
const scanMock = vi.hoisted(() => vi.fn());
const completeMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/documents_receiving", () => ({
  documentsReceivingApi: {
    startWmsReceiving: startWmsReceivingMock,
    wmsReceivingScan: scanMock,
    wmsReceivingShortReceive: shortReceiveMock,
    wmsReceivingSkip: vi.fn(),
    wmsReceivingUndo: vi.fn(),
    wmsReceivingComplete: completeMock,
    wmsReceivingCancel: vi.fn(),
    wmsReceivingPause: vi.fn().mockResolvedValue(undefined),
  },
}));

const line: WmsReceiveLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  from_order: false,
  expected_is_count: false,
  pick_order: 1,
  status: "pending",
  received_quantity: 0,
  product_name: "Widget",
  lot_name: null,
  expected_quantity: 5,
  uom_symbol: "pcs",
};

function buildSession(lines: WmsReceiveLine[]): WmsReceiveSession {
  return {
    id: "session-1",
    document_id: "doc-1",
    assigned_to: null,
    status: "active",
    started_at: null,
    completed_at: null,
    lines,
    total_lines: lines.length,
    received_lines: 0,
    pending_lines: lines.length,
    shelf_scan_required: false,
  };
}

type HookResult = ReturnType<typeof useWmsReceiving>;

async function startSessionWithLine(): Promise<
  RenderHookResult<HookResult, unknown>
> {
  startWmsReceivingMock.mockResolvedValue(buildSession([line]));
  const utils = renderHook(() => useWmsReceiving("doc-1"), {
    wrapper: QueryWrapper,
  });
  await act(async () => {
    await utils.result.current.startSession();
  });
  return utils;
}

describe("useWmsReceiving.confirmShortReceive", () => {
  it("marks a full-quantity receive as received, not short", async () => {
    shortReceiveMock.mockResolvedValue({
      status: "short_receive_confirmed",
      line_id: "line-1",
      product_name: "Widget",
      received_quantity: 5,
      expected_quantity: 5,
      uom_symbol: "pcs",
      message: "Short receive: 5/5",
      session_complete: true,
    });
    const utils = await startSessionWithLine();

    const outcome = await act(async () =>
      utils.result.current.confirmShortReceive("line-1", 5, ""),
    );

    expect(outcome?.status).toBe("received");
    expect(utils.result.current.state.lines[0].status).toBe("received");
    expect(utils.result.current.state.lines[0].received_quantity).toBe(5);
  });

  it("marks a partial receive as short and keeps the phase active", async () => {
    shortReceiveMock.mockResolvedValue({
      status: "short_receive_confirmed",
      line_id: "line-1",
      product_name: "Widget",
      received_quantity: 2,
      expected_quantity: 5,
      uom_symbol: "pcs",
      message: "Short receive: 2/5",
      session_complete: false,
    });
    const utils = await startSessionWithLine();

    const outcome = await act(async () =>
      utils.result.current.confirmShortReceive("line-1", 2, "SHORTAGE"),
    );

    expect(outcome?.status).toBe("short");
    expect(utils.result.current.state.lines[0].status).toBe("short");
    expect(utils.result.current.state.phase).toBe("active");
  });
});

describe("useWmsReceiving.scan", () => {
  it("leaves a part-delivered line open, so the shortage can still be reported", async () => {
    // The server answers "received" for every accepted scan, partial ones
    // included. Reading that word as the line's status marked 5 of 12.5 as a
    // complete delivery: the scan field went away, and so did "Short receive"
    // and "Skip", in the one situation they exist for.
    scanMock.mockResolvedValue({
      status: "received",
      line_id: "line-1",
      product_name: "Widget",
      received_quantity: 2,
      expected_quantity: 5,
      uom_symbol: "pcs",
      message: "Widget received — 2/5 pcs",
      session_complete: false,
    });
    const utils = await startSessionWithLine();

    await act(async () => {
      await utils.result.current.scan("BARCODE", 2);
    });

    expect(utils.result.current.state.lines[0].status).toBe("pending");
    expect(utils.result.current.state.lines[0].received_quantity).toBe(2);
    expect(utils.result.current.state.phase).toBe("active");
    expect(utils.result.current.pendingCount).toBe(1);
  });

  it("marks a line received once the scan reaches the expected quantity", async () => {
    scanMock.mockResolvedValue({
      status: "received",
      line_id: "line-1",
      product_name: "Widget",
      received_quantity: 5,
      expected_quantity: 5,
      uom_symbol: "pcs",
      message: "Widget received — 5/5 pcs",
      session_complete: true,
    });
    const utils = await startSessionWithLine();

    await act(async () => {
      await utils.result.current.scan("BARCODE", 5);
    });

    expect(utils.result.current.state.lines[0].status).toBe("received");
    expect(utils.result.current.state.phase).toBe("completed");
  });
});

describe("useWmsReceiving.completeSession", () => {
  it("reports the server's refusal, so no success message can follow it", async () => {
    // "Receiving completed" used to appear next to "Cannot complete: 1 lines
    // still pending", because the caller had no way to tell the two apart.
    completeMock.mockRejectedValue(
      Object.assign(new Error("refused"), {
        response: {
          status: 400,
          data: { detail: "Cannot complete: 1 lines still pending" },
        },
      }),
    );
    const utils = await startSessionWithLine();

    const closed = await act(async () =>
      utils.result.current.completeSession(),
    );

    expect(closed).toBe(false);
    expect(utils.result.current.state.phase).toBe("active");
  });

  it("reports success when the server closed the session", async () => {
    completeMock.mockResolvedValue({});
    const utils = await startSessionWithLine();

    const closed = await act(async () =>
      utils.result.current.completeSession(),
    );

    expect(closed).toBe(true);
    expect(utils.result.current.state.phase).toBe("completed");
  });
});

describe("useWmsReceiving failure context", () => {
  it("leaves the sentence to the view when the scan fails with nothing to show", async () => {
    // A 5xx detail is written for the logs, and a hard-coded fallback was an
    // English sentence a Polish reader would meet. The hook carries what the
    // API said, if it said anything, and names the action that failed — the
    // words come from the namespace.
    scanMock.mockRejectedValue(
      Object.assign(new Error("boom"), { response: { status: 500 } }),
    );
    const utils = await startSessionWithLine();

    await act(async () => {
      await utils.result.current.scan("BARCODE", 1);
    });

    expect(utils.result.current.error).toBeNull();
    expect(utils.result.current.errorContext).toBe("scan");
  });
});
