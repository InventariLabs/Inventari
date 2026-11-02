import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { DocumentsListParams } from "@/modules/warehouse/api/documents";
import { useDocuments } from "@/modules/warehouse/hooks/useDocuments";
import { useDocumentHistory } from "./useDocumentHistory";

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useDocuments: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentContributions", async () => {
  const actual = await vi.importActual<
    typeof import("@/modules/warehouse/hooks/useDocumentContributions")
  >("@/modules/warehouse/hooks/useDocumentContributions");
  return {
    ...actual,
    useDocumentListContributions: () => ({ columns: [], filters: [] }),
  };
});

/** The params of the most recent list request the hook made. */
function lastParams(): DocumentsListParams {
  const calls = vi.mocked(useDocuments).mock.calls;
  return calls[calls.length - 1][0] as DocumentsListParams;
}

/**
 * The History list's paging and toggles. A pager that walked past the last
 * page asked for an empty one; a "drafts and planned" toggle that kept the
 * completion order put work typed in today behind last week's entries.
 */
describe("useDocumentHistory — paging, the planned toggle and clearing filters", () => {
  beforeEach(() => {
    vi.mocked(useDocuments).mockReturnValue({
      data: { items: [], total: 120 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useDocuments>);
  });

  it("pages forward, stops at the last page, and pages back without going below zero", () => {
    const { result } = renderHook(() => useDocumentHistory());

    act(() => result.current.onNext());
    expect(lastParams().offset).toBe(50);
    act(() => result.current.onNext());
    expect(lastParams().offset).toBe(100);
    act(() => result.current.onNext());
    expect(lastParams().offset).toBe(100);

    act(() => result.current.onPrev());
    act(() => result.current.onPrev());
    act(() => result.current.onPrev());
    expect(lastParams().offset).toBe(0);

    act(() => result.current.onPageChange(3));
    expect(result.current.skip).toBe(100);
  });

  it("lists the planned work by when it was typed in, from the first page", () => {
    const { result } = renderHook(() => useDocumentHistory());
    act(() => result.current.onPageChange(2));

    act(() => result.current.togglePlanned());

    expect(result.current.planned).toBe(true);
    expect(lastParams()).toMatchObject({
      status: "DRAFT,PENDING_APPROVAL,CONFIRMED",
      sort_by: "created_at",
      offset: 0,
    });
  });

  it("clears the search and the kind chip, and says so through isNarrowed", () => {
    const { result } = renderHook(() => useDocumentHistory());

    act(() => {
      result.current.setSearch("pallet");
      result.current.setChip("receipts");
    });
    expect(result.current.isNarrowed).toBe(true);
    expect(lastParams().type).toBe("IN,INTERNAL_IN");

    act(() => result.current.clearFilters());

    expect(result.current.search).toBe("");
    expect(result.current.chip).toBe("all");
    expect(result.current.isNarrowed).toBe(false);
    expect(lastParams().type).toBeUndefined();
  });
});
