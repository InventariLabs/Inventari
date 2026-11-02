import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useBulkSelect } from "./useBulkSelect";
import type { WarehouseDocumentRow } from "@/modules/warehouse/types";

function makeDoc(id: string, status: string): WarehouseDocumentRow {
  return {
    id,
    number: `IN/${id}`,
    type: "IN",
    status: status as WarehouseDocumentRow["status"],
    partner_id: null,
    source_location_id: null,
    target_location_id: null,
    scheduled_date: null,
    notes: null,
    external_reference: null,
    created_at: "2024-01-01",
    organization_id: "org",
    created_by: "user",
    document_currency: "USD",
    currency: "USD",
    partner_snapshot: null,
    lines: [],
    number_padding: null,
    total_gross: null,
    total_net: null,
    total_tax: null,
    confirmed_at: null,
    completed_at: null,
    cancelled_at: null,
  } as unknown as WarehouseDocumentRow;
}

describe("useBulkSelect", () => {
  const emptyDelete = { mutate: vi.fn() };

  it("starts with empty selection", () => {
    const { result } = renderHook(() =>
      useBulkSelect({
        documents: [makeDoc("1", "DRAFT"), makeDoc("2", "CONFIRMED")],
        deleteMutation: emptyDelete,
        confirmMutation: emptyDelete,
      }),
    );
    expect(result.current.selectedIds.size).toBe(0);
    expect(result.current.selectedDrafts).toEqual([]);
    expect(result.current.selectedDocs).toEqual([]);
  });

  it("toggleSelect adds then removes an id", () => {
    const { result } = renderHook(() =>
      useBulkSelect({
        documents: [makeDoc("1", "DRAFT")],
        deleteMutation: emptyDelete,
        confirmMutation: emptyDelete,
      }),
    );
    act(() => result.current.toggleSelect("1"));
    expect(result.current.selectedIds.has("1")).toBe(true);
    act(() => result.current.toggleSelect("1"));
    expect(result.current.selectedIds.has("1")).toBe(false);
  });

  it("selectAll selects all then clears on second call", () => {
    const docs = [
      makeDoc("1", "DRAFT"),
      makeDoc("2", "DRAFT"),
      makeDoc("3", "CONFIRMED"),
    ];
    const { result } = renderHook(() =>
      useBulkSelect({
        documents: docs,
        deleteMutation: emptyDelete,
        confirmMutation: emptyDelete,
      }),
    );
    act(() => result.current.toggleSelectAll());
    expect(result.current.selectedIds.size).toBe(3);
    act(() => result.current.toggleSelectAll());
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("selectedDrafts filters to DRAFT only", () => {
    const docs = [
      makeDoc("1", "DRAFT"),
      makeDoc("2", "CONFIRMED"),
      makeDoc("3", "DRAFT"),
    ];
    const { result } = renderHook(() =>
      useBulkSelect({
        documents: docs,
        deleteMutation: emptyDelete,
        confirmMutation: emptyDelete,
      }),
    );
    act(() => result.current.toggleSelect("1"));
    act(() => result.current.toggleSelect("2"));
    act(() => result.current.toggleSelect("3"));
    expect(result.current.selectedDrafts.map((d) => d.id)).toEqual(["1", "3"]);
  });

  it("drops a tick whose row the next page no longer carries", () => {
    // The bar counts what it can act on, and one page's ticks used to stay
    // in the set while the actions were built from the page in view: the
    // session covered one document and the other stayed ticked out of sight.
    const page1 = [makeDoc("1", "CONFIRMED"), makeDoc("2", "CONFIRMED")];
    const page2 = [makeDoc("3", "CONFIRMED")];
    const { result, rerender } = renderHook(
      ({ documents }: { documents: WarehouseDocumentRow[] }) =>
        useBulkSelect({
          documents,
          deleteMutation: emptyDelete,
          confirmMutation: emptyDelete,
        }),
      { initialProps: { documents: page1 } },
    );
    act(() => {
      result.current.toggleSelect("1");
      result.current.toggleSelect("2");
    });
    expect(result.current.selectedIds.size).toBe(2);

    rerender({ documents: page2 });

    expect(result.current.selectedIds.size).toBe(0);
    expect(result.current.selectedDocs).toEqual([]);
  });

  it("keeps the ticks when the same page is fetched again", () => {
    // A refetch hands over a new array of the same rows; the ticks are about
    // the rows, not the array's identity.
    const { result, rerender } = renderHook(
      ({ documents }: { documents: WarehouseDocumentRow[] }) =>
        useBulkSelect({
          documents,
          deleteMutation: emptyDelete,
          confirmMutation: emptyDelete,
        }),
      { initialProps: { documents: [makeDoc("1", "CONFIRMED")] } },
    );
    act(() => result.current.toggleSelect("1"));

    rerender({ documents: [makeDoc("1", "CONFIRMED")] });

    expect(result.current.selectedIds.has("1")).toBe(true);
  });

  it("clearSelection empties the selection", () => {
    const { result } = renderHook(() =>
      useBulkSelect({
        documents: [makeDoc("1", "DRAFT")],
        deleteMutation: emptyDelete,
        confirmMutation: emptyDelete,
      }),
    );
    act(() => result.current.toggleSelect("1"));
    act(() => result.current.clearSelection());
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("handleBulkDelete deletes only draft docs", async () => {
    const mutate = vi.fn((_id, opts) => opts?.onSuccess?.());
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const docs = [
      makeDoc("1", "DRAFT"),
      makeDoc("2", "CONFIRMED"),
      makeDoc("3", "DRAFT"),
    ];
    const { result } = renderHook(() =>
      useBulkSelect({
        documents: docs,
        deleteMutation: { mutate },
        confirmMutation: emptyDelete,
        onSuccess,
        onError,
      }),
    );
    act(() => {
      result.current.toggleSelect("1");
      result.current.toggleSelect("2");
      result.current.toggleSelect("3");
    });
    await act(async () => {
      await result.current.handleBulkDelete();
    });
    // Mutate must have been called exactly for draft docs (1 and 3), not confirmed (2)
    expect(mutate).toHaveBeenCalledTimes(2);
    expect(mutate.mock.calls.map((c) => c[0])).toEqual(["1", "3"]);
    expect(onSuccess).toHaveBeenCalledWith(2);
    expect(result.current.selectedIds.size).toBe(0);
    expect(result.current.bulkDeleteOpen).toBe(false);
  });

  it("handleBulkConfirm confirms the drafts and names each refusal", async () => {
    const refusal = new Error("stock too low");
    const confirm = vi.fn((id: string, opts) =>
      id === "3" ? opts?.onError?.(refusal) : opts?.onSuccess?.(),
    );
    const onConfirmed = vi.fn();
    const docs = [
      makeDoc("1", "DRAFT"),
      makeDoc("2", "CONFIRMED"),
      makeDoc("3", "DRAFT"),
      makeDoc("4", "DRAFT"),
    ];
    const { result } = renderHook(() =>
      useBulkSelect({
        documents: docs,
        deleteMutation: emptyDelete,
        confirmMutation: { mutate: confirm },
        onConfirmed,
      }),
    );
    act(() => {
      docs.forEach((d) => result.current.toggleSelect(d.id));
    });
    await act(async () => {
      await result.current.handleBulkConfirm();
    });
    // Only drafts are tried, in list order; the confirmed one is left alone.
    expect(confirm.mock.calls.map((c) => c[0])).toEqual(["1", "3", "4"]);
    expect(onConfirmed).toHaveBeenCalledWith(2, [
      { doc: docs[2], error: refusal },
    ]);
    // The refused draft stays selected so it can be fixed and retried.
    expect([...result.current.selectedIds]).toEqual(["3"]);
  });
});
