import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useWmsPicking } from "../useWmsPicking";
import { useWmsReceiving } from "../useWmsReceiving";
import type { WmsPickLine, WmsPickSession } from "../../api/documents_picking";
import type {
  WmsReceiveLine,
  WmsReceiveSession,
} from "../../api/documents_receiving";

const picking = vi.hoisted(() => ({
  start: vi.fn(),
  skip: vi.fn(),
  undo: vi.fn(),
  complete: vi.fn(),
  cancel: vi.fn(),
  pause: vi.fn(),
}));
const receiving = vi.hoisted(() => ({
  start: vi.fn(),
  skip: vi.fn(),
  undo: vi.fn(),
  complete: vi.fn(),
  cancel: vi.fn(),
  pause: vi.fn(),
}));

vi.mock("../../api/documents", () => ({
  documentsApi: {
    startWmsPicking: picking.start,
    wmsPickingScan: vi.fn(),
    wmsPickingShortPick: vi.fn(),
    wmsPickingSkip: picking.skip,
    wmsPickingUndo: picking.undo,
    wmsPickingComplete: picking.complete,
    wmsPickingCancel: picking.cancel,
    wmsPickingPause: picking.pause,
  },
}));

vi.mock("../../api/documents_receiving", () => ({
  documentsReceivingApi: {
    startWmsReceiving: receiving.start,
    wmsReceivingScan: vi.fn(),
    wmsReceivingShortReceive: vi.fn(),
    wmsReceivingSkip: receiving.skip,
    wmsReceivingUndo: receiving.undo,
    wmsReceivingComplete: receiving.complete,
    wmsReceivingCancel: receiving.cancel,
    wmsReceivingPause: receiving.pause,
  },
}));

const pickLine: WmsPickLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  pick_order: 1,
  status: "pending",
  picked_quantity: 3,
  bin_location: null,
  product_name: "Kawa mielona Jacobs",
  lot_name: null,
  expected_quantity: 4,
  uom_symbol: "pcs",
};

const receiveLine: WmsReceiveLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  from_order: false,
  pick_order: 1,
  status: "pending",
  received_quantity: 3,
  product_name: "Kawa mielona Jacobs",
  lot_name: null,
  expected_quantity: 4,
  uom_symbol: "pcs",
};

const pickSession: WmsPickSession = {
  id: "session-1",
  document_id: "doc-1",
  assigned_to: null,
  status: "active",
  started_at: null,
  completed_at: null,
  lines: [pickLine],
  total_lines: 1,
  picked_lines: 0,
  pending_lines: 1,
  shelf_scan_required: false,
  documents: [],
};

const receiveSession: WmsReceiveSession = {
  id: "session-1",
  document_id: "doc-1",
  assigned_to: null,
  status: "active",
  started_at: null,
  completed_at: null,
  lines: [receiveLine],
  total_lines: 1,
  received_lines: 0,
  pending_lines: 1,
  shelf_scan_required: false,
};

// The client the hooks invalidate through, so a test can see what was
// refreshed after the screen went away.
let queryClient = new QueryClient();
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

/**
 * Each side, reduced to the half of its surface the shared machine answers
 * for. The two objects are structurally identical on purpose — that is the
 * claim under test.
 */
const SIDES = [
  {
    name: "picking",
    api: picking,
    async render() {
      picking.start.mockResolvedValue(pickSession);
      const { result, unmount } = renderHook(() => useWmsPicking("doc-1"), {
        wrapper,
      });
      await act(async () => {
        await result.current.startSession();
      });
      return {
        phase: () => result.current.state.phase as string,
        lineStatus: () => result.current.state.lines[0].status as string,
        lineQuantity: () => result.current.state.lines[0].picked_quantity,
        pendingCount: () => result.current.pendingCount,
        errorContext: () => result.current.errorContext as string | null,
        skip: (lineId: string) => result.current.skipLine(lineId),
        undo: (lineId: string) => result.current.undoLine(lineId),
        complete: () => result.current.completeSession(),
        cancel: () => result.current.cancelSession(),
        unmount,
      };
    },
  },
  {
    name: "receiving",
    api: receiving,
    async render() {
      receiving.start.mockResolvedValue(receiveSession);
      const { result, unmount } = renderHook(() => useWmsReceiving("doc-1"), {
        wrapper,
      });
      await act(async () => {
        await result.current.startSession();
      });
      return {
        phase: () => result.current.state.phase as string,
        lineStatus: () => result.current.state.lines[0].status as string,
        lineQuantity: () => result.current.state.lines[0].received_quantity,
        pendingCount: () => result.current.pendingCount,
        errorContext: () => result.current.errorContext as string | null,
        skip: (lineId: string) => result.current.skipLine(lineId),
        undo: (lineId: string) => result.current.undoLine(lineId),
        complete: () => result.current.completeSession(),
        cancel: () => result.current.cancelSession(),
        unmount,
      };
    },
  },
] as const;

/**
 * Picking and receiving run the same session machine, so the actions that
 * are not about scanning have to answer identically on both.
 *
 * They used to be two hand-kept copies, and each repair landed on one side
 * only: `completeSession` learned to report the server's refusal in
 * receiving while picking kept firing a success toast next to it. This is
 * the test that would have said so.
 */
describe.each(SIDES)("useWmsSession through $name", (side) => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient();
  });

  it("closing the sheet over an open session pauses it", async () => {
    side.api.pause.mockResolvedValue(undefined);
    const session = await side.render();

    session.unmount();

    expect(side.api.pause).toHaveBeenCalledWith("doc-1", "session-1");
  });

  // The sheet's close refreshes the document before the pause it sets off
  // has landed, so the notice read the session as still active and offered
  // no completion until a reload. The refresh that counts is the one after.
  it("the documents are read again once the pause has landed", async () => {
    let landPause: () => void = () => {};
    side.api.pause.mockReturnValue(
      new Promise<void>((resolve) => {
        landPause = resolve;
      }),
    );
    const session = await side.render();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    session.unmount();
    expect(invalidate).not.toHaveBeenCalled();
    landPause();

    await waitFor(() =>
      // The prefix, not the one document: the To do list is a query under it.
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["documents"] }),
    );
  });

  it("closing the sheet after a cancel pauses nothing", async () => {
    side.api.cancel.mockResolvedValue(undefined);
    const session = await side.render();
    await act(async () => {
      await session.cancel();
    });

    session.unmount();

    expect(side.api.pause).not.toHaveBeenCalled();
  });

  it("skipping the last pending line closes the session", async () => {
    side.api.skip.mockResolvedValue(undefined);
    const session = await side.render();

    const skipped = await act(async () => session.skip("line-1"));

    expect(skipped).toBe(true);
    expect(session.lineStatus()).toBe("skipped");
    expect(session.lineQuantity()).toBe(0);
    expect(session.phase()).toBe("completed");
  });

  it("undo puts the line back and reopens the session", async () => {
    side.api.skip.mockResolvedValue(undefined);
    side.api.undo.mockResolvedValue(undefined);
    const session = await side.render();

    await act(async () => {
      await session.skip("line-1");
    });
    await act(async () => {
      await session.undo("line-1");
    });

    expect(session.lineStatus()).toBe("pending");
    expect(session.phase()).toBe("active");
    expect(session.pendingCount()).toBe(1);
  });

  it("a completed undo reports success", async () => {
    side.api.undo.mockResolvedValue(undefined);
    const session = await side.render();

    const undone = await act(async () => session.undo("line-1"));

    expect(undone).toBe(true);
    expect(session.lineStatus()).toBe("pending");
    expect(session.errorContext()).toBeNull();
  });

  it("a refused undo is reported, not celebrated", async () => {
    // What the packing guard answers with: the line stays counted and the
    // session stands, so the caller has nothing to announce.
    side.api.undo.mockRejectedValue(new Error("a package already holds 6"));
    const session = await side.render();

    const undone = await act(async () => session.undo("line-1"));

    expect(undone).toBe(false);
    expect(session.lineStatus()).toBe("pending");
    expect(session.lineQuantity()).toBe(3);
    expect(session.phase()).toBe("active");
    expect(session.errorContext()).toBe("undo");
  });

  it("completing says whether the server closed the session", async () => {
    side.api.complete.mockResolvedValue(undefined);
    const session = await side.render();

    const closed = await act(async () => session.complete());

    expect(closed).toBe(true);
    expect(session.phase()).toBe("completed");
  });

  it("a refused completion is reported, not celebrated", async () => {
    side.api.complete.mockRejectedValue(new Error("1 lines still pending"));
    const session = await side.render();

    const closed = await act(async () => session.complete());

    expect(closed).toBe(false);
    expect(session.phase()).toBe("active");
    expect(session.errorContext()).toBe("complete");
  });

  it("a refused action names itself and leaves the lines alone", async () => {
    side.api.skip.mockRejectedValue(new Error("boom"));
    const session = await side.render();

    const skipped = await act(async () => session.skip("line-1"));

    expect(skipped).toBe(false);
    expect(session.errorContext()).toBe("skip");
    expect(session.lineStatus()).toBe("pending");
  });

  it("cancelling says whether the server ended the session", async () => {
    side.api.cancel.mockResolvedValue(undefined);
    const session = await side.render();

    const cancelled = await act(async () => session.cancel());

    expect(cancelled).toBe(true);
    expect(session.phase()).toBe("cancelled");
  });

  it("a refused cancel is reported and the session stays open", async () => {
    side.api.cancel.mockRejectedValue(new Error("session is locked"));
    const session = await side.render();

    const cancelled = await act(async () => session.cancel());

    expect(cancelled).toBe(false);
    expect(session.phase()).toBe("active");
    expect(session.errorContext()).toBe("cancel");
  });
});
