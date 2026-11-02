import { QueryWrapper } from "@/test/queryWrapper";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useWmsReceiving } from "../useWmsReceiving";
import type {
  WmsReceiveLine,
  WmsReceiveSession,
} from "../../api/documents_receiving";

const startMock = vi.hoisted(() => vi.fn());
const shortReceiveMock = vi.hoisted(() => vi.fn());
const skipMock = vi.hoisted(() => vi.fn());
const getSessionMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/documents_receiving", () => ({
  documentsReceivingApi: {
    startWmsReceiving: startMock,
    wmsReceivingScan: vi.fn(),
    wmsReceivingShortReceive: shortReceiveMock,
    wmsReceivingSkip: skipMock,
    wmsReceivingUndo: vi.fn(),
    wmsReceivingComplete: vi.fn(),
    wmsReceivingCancel: vi.fn(),
    wmsReceivingPause: vi.fn().mockResolvedValue(undefined),
    getWmsReceivingSession: getSessionMock,
  },
}));

function line(
  id: string,
  status: WmsReceiveLine["status"],
  received: number,
): WmsReceiveLine {
  return {
    id,
    document_line_id: `doc-${id}`,
    from_order: false,
    pick_order: 1,
    status,
    received_quantity: received,
    product_name: id,
    lot_name: null,
    expected_quantity: 10,
    uom_symbol: "pcs",
  };
}

function session(
  lines: WmsReceiveLine[],
  status = "active",
): WmsReceiveSession {
  return {
    id: "session-1",
    document_id: "doc-1",
    assigned_to: null,
    status,
    started_at: null,
    completed_at: null,
    lines,
    total_lines: lines.length,
    received_lines: 0,
    pending_lines: 0,
    shelf_scan_required: false,
  };
}

async function started(lines: WmsReceiveLine[]) {
  startMock.mockResolvedValue(session(lines));
  const utils = renderHook(() => useWmsReceiving("doc-1"), {
    wrapper: QueryWrapper,
  });
  await act(async () => {
    await utils.result.current.startSession();
  });
  return utils;
}

describe("useWmsReceiving.finishWithoutRest", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    shortReceiveMock.mockResolvedValue({ status: "short_receive_confirmed" });
    skipMock.mockResolvedValue({ status: "skipped" });
  });

  it("closes every open line with what arrived of it and reads the closed session back", async () => {
    const utils = await started([
      line("done", "received", 10),
      line("partial", "pending", 3),
      line("missing", "pending", 0),
    ]);
    const closed = session(
      [
        line("done", "received", 10),
        line("partial", "short", 3),
        line("missing", "short", 0),
      ],
      "completed",
    );
    getSessionMock.mockResolvedValue(closed);

    let finished = false;
    await act(async () => {
      finished = await utils.result.current.finishWithoutRest();
    });

    expect(finished).toBe(true);
    // What was already counted of a line stays counted: a skip would empty it.
    expect(shortReceiveMock).toHaveBeenCalledTimes(2);
    expect(shortReceiveMock).toHaveBeenCalledWith(
      "doc-1",
      "session-1",
      "partial",
      3,
    );
    // Nothing of it arrived: the line is answered with a count of nothing,
    // not skipped — a skip carries no reason, and completing the phone
    // delivery right after would be refused for it.
    expect(shortReceiveMock).toHaveBeenCalledWith(
      "doc-1",
      "session-1",
      "missing",
      0,
    );
    expect(skipMock).not.toHaveBeenCalled();
    expect(utils.result.current.state.phase).toBe("completed");
    expect(utils.result.current.state.lines.map((ln) => ln.status)).toEqual([
      "received",
      "short",
      "short",
    ]);
  });

  it("shows the server's state after a refusal halfway, not the screen's guess", async () => {
    const utils = await started([
      line("first", "pending", 0),
      line("second", "pending", 0),
    ]);
    shortReceiveMock
      .mockResolvedValueOnce({ status: "short_receive_confirmed" })
      .mockRejectedValueOnce(new Error("boom"));
    getSessionMock.mockResolvedValue(
      session([line("first", "short", 0), line("second", "pending", 0)]),
    );

    let finished = true;
    await act(async () => {
      finished = await utils.result.current.finishWithoutRest();
    });

    expect(finished).toBe(false);
    expect(utils.result.current.state.phase).toBe("active");
    expect(utils.result.current.state.lines.map((ln) => ln.status)).toEqual([
      "short",
      "pending",
    ]);
    expect(utils.result.current.errorContext).toBe("skip");
  });
});
