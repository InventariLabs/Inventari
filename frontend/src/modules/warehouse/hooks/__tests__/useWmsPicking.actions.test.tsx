import { QueryWrapper } from "@/test/queryWrapper";
import { describe, expect, it, vi } from "vitest";
import { act, renderHook, type RenderHookResult } from "@testing-library/react";
import { useWmsPicking } from "../useWmsPicking";
import type { WmsPickLine, WmsPickSession } from "../../api/documents_picking";

const startWmsPickingMock = vi.hoisted(() => vi.fn());
const shortPickMock = vi.hoisted(() => vi.fn());
const scanMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/documents", () => ({
  documentsApi: {
    startWmsPicking: startWmsPickingMock,
    wmsPickingScan: scanMock,
    wmsPickingShortPick: shortPickMock,
    wmsPickingSkip: vi.fn(),
    wmsPickingUndo: vi.fn(),
    wmsPickingComplete: vi.fn(),
    wmsPickingCancel: vi.fn(),
    wmsPickingPause: vi.fn().mockResolvedValue(undefined),
  },
}));

const line: WmsPickLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  pick_order: 1,
  status: "pending",
  picked_quantity: 0,
  bin_location: null,
  product_name: "Kawa mielona Jacobs",
  lot_name: null,
  expected_quantity: 4,
  uom_symbol: "pcs",
};

function buildSession(lines: WmsPickLine[]): WmsPickSession {
  return {
    id: "session-1",
    document_id: "doc-1",
    assigned_to: null,
    status: "active",
    started_at: null,
    completed_at: null,
    lines,
    total_lines: lines.length,
    picked_lines: 0,
    pending_lines: lines.length,
    shelf_scan_required: false,
    documents: [],
  };
}

type HookResult = ReturnType<typeof useWmsPicking>;

async function startSessionWithLine(): Promise<
  RenderHookResult<HookResult, unknown>
> {
  startWmsPickingMock.mockResolvedValue(buildSession([line]));
  const utils = renderHook(() => useWmsPicking("doc-1"), {
    wrapper: QueryWrapper,
  });
  await act(async () => {
    await utils.result.current.startSession();
  });
  return utils;
}

/**
 * The shortage dialog is not only for shortages: a product with no barcode
 * can be picked no other way. So the status this path writes has to come
 * from the quantities, exactly as the receiving twin already derives it —
 * the earlier fix landed on one of the two sides.
 */
describe("useWmsPicking.confirmShortPick", () => {
  it("marks a full-quantity pick as picked, not short", async () => {
    shortPickMock.mockResolvedValue({
      status: "short_pick_confirmed",
      line_id: "line-1",
      product_name: "Kawa mielona Jacobs",
      picked_quantity: 4,
      expected_quantity: 4,
      uom_symbol: "pcs",
      bin_location: null,
      message: "Short pick: 4/4",
      session_complete: true,
    });
    const utils = await startSessionWithLine();

    const outcome = await act(async () =>
      utils.result.current.confirmShortPick("line-1", 4, "SHORTAGE"),
    );

    expect(outcome?.status).toBe("picked");
    expect(utils.result.current.state.lines[0].status).toBe("picked");
    expect(utils.result.current.state.lines[0].picked_quantity).toBe(4);
  });

  it("marks a partial pick as short", async () => {
    shortPickMock.mockResolvedValue({
      status: "short_pick_confirmed",
      line_id: "line-1",
      product_name: "Kawa mielona Jacobs",
      picked_quantity: 3,
      expected_quantity: 4,
      uom_symbol: "pcs",
      bin_location: null,
      message: "Short pick: 3/4",
      session_complete: false,
    });
    const utils = await startSessionWithLine();

    const outcome = await act(async () =>
      utils.result.current.confirmShortPick("line-1", 3, "SHORTAGE"),
    );

    expect(outcome?.status).toBe("short");
    expect(utils.result.current.state.lines[0].status).toBe("short");
    expect(utils.result.current.state.phase).toBe("active");
  });

  it("says nothing happened when the server refused", async () => {
    shortPickMock.mockRejectedValue(new Error("boom"));
    const utils = await startSessionWithLine();

    const outcome = await act(async () =>
      utils.result.current.confirmShortPick("line-1", 4, "SHORTAGE"),
    );

    expect(outcome).toBeNull();
    expect(utils.result.current.state.lines[0].status).toBe("pending");
  });
});

/**
 * The date beside the batch is the batch's: a scan that names another batch
 * than the plan moves the row to it, and the date moves with it.
 */
describe("useWmsPicking.scan", () => {
  const scanAnswer = {
    status: "picked",
    line_id: "line-1",
    product_name: "Kawa mielona Jacobs",
    picked_quantity: 4,
    expected_quantity: 4,
    uom_symbol: "pcs",
    bin_location: null,
    message: "",
    session_complete: false,
  };

  it("takes the date of the batch the scan named", async () => {
    startWmsPickingMock.mockResolvedValue(
      buildSession([{ ...line, lot_name: "L-1", expiry_date: "2026-10-25" }]),
    );
    scanMock.mockResolvedValue({
      ...scanAnswer,
      lot_name: "L-2",
      expiry_date: "2026-12-01",
    });
    const utils = renderHook(() => useWmsPicking("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await utils.result.current.startSession();
    });

    await act(async () => {
      await utils.result.current.scan("123", 4);
    });

    expect(utils.result.current.state.lines[0].lot_name).toBe("L-2");
    expect(utils.result.current.state.lines[0].expiry_date).toBe("2026-12-01");
  });

  it("keeps the planned date when the scan names no other batch", async () => {
    startWmsPickingMock.mockResolvedValue(
      buildSession([{ ...line, lot_name: null, expiry_date: "2026-10-25" }]),
    );
    scanMock.mockResolvedValue({ ...scanAnswer, lot_name: null });
    const utils = renderHook(() => useWmsPicking("doc-1"), {
      wrapper: QueryWrapper,
    });
    await act(async () => {
      await utils.result.current.startSession();
    });

    await act(async () => {
      await utils.result.current.scan("123", 4);
    });

    expect(utils.result.current.state.lines[0].expiry_date).toBe("2026-10-25");
  });
});
