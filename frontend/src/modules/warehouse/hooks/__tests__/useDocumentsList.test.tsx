import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";

import { useDocumentsList } from "@/modules/warehouse/hooks/useDocumentsList";
import * as documentsHooks from "@/modules/warehouse/hooks/useDocuments";

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useDocuments: vi.fn(),
}));

/** The hook reads ?partner_id= from the URL, so it needs a router. */
function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

/** Drive `useMediaQuery` without a real layout engine. */
function setViewportMatches(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

describe("useDocumentsList page size", () => {
  const mockedUseDocuments = vi.mocked(documentsHooks.useDocuments);

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseDocuments.mockReturnValue({
      data: { items: [], total: 120 },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);
  });

  it("asks for fewer rows on a narrow screen", () => {
    // 50 rows made the mobile page 17,000px tall, with the pager at the very
    // bottom of it.
    setViewportMatches(false);
    const { result } = renderHook(() => useDocumentsList(), { wrapper });
    expect(result.current.limit).toBe(20);
  });

  it("keeps the desktop page size on a wide screen", () => {
    setViewportMatches(true);
    const { result } = renderHook(() => useDocumentsList(), { wrapper });
    expect(result.current.limit).toBe(50);
  });

  it("lets the caller's explicit limit win over the responsive default", () => {
    setViewportMatches(false);
    const { result } = renderHook(() => useDocumentsList({ limit: 100 }), {
      wrapper,
    });
    expect(result.current.limit).toBe(100);
  });

  it("honours a page size the user picked, and returns to page one", () => {
    setViewportMatches(true);
    const { result } = renderHook(() => useDocumentsList(), { wrapper });

    act(() => result.current.onNext());
    expect(result.current.skip).toBe(50);

    act(() => result.current.onLimitChange(20));
    expect(result.current.limit).toBe(20);
    expect(result.current.skip).toBe(0);
  });

  it("jumps to a page instead of stepping through every one", () => {
    setViewportMatches(true);
    const { result } = renderHook(() => useDocumentsList(), { wrapper });

    act(() => result.current.onPageChange(3));
    expect(result.current.skip).toBe(100);
  });
});

describe("useDocumentsList filters in the URL", () => {
  const mockedUseDocuments = vi.mocked(documentsHooks.useDocuments);

  beforeEach(() => {
    vi.clearAllMocks();
    setViewportMatches(true);
    mockedUseDocuments.mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocuments>);
  });

  function at(url: string) {
    return ({ children }: { children: ReactNode }) => (
      <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>
    );
  }

  it("reads type, status and the date range off the address", () => {
    const { result } = renderHook(() => useDocumentsList(), {
      wrapper: at(
        "/warehouse?type=OUT&status=CONFIRMED&date_from=2026-10-01&date_to=2026-10-16",
      ),
    });

    expect(result.current.typeFilter).toBe("OUT");
    expect(result.current.statusFilter).toBe("CONFIRMED");
    expect(result.current.dateFrom).toBe("2026-10-01");
    expect(result.current.dateTo).toBe("2026-10-16");
    expect(mockedUseDocuments).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: "OUT",
        status: "CONFIRMED",
        date_from: "2026-10-01",
        date_to: "2026-10-16",
      }),
    );
  });

  it("ignores a value that is not a type or a status", () => {
    const { result } = renderHook(() => useDocumentsList(), {
      wrapper: at("/warehouse?type=BOGUS&status=whatever"),
    });

    expect(result.current.typeFilter).toBe("ALL");
    expect(result.current.statusFilter).toBe("ALL");
  });

  it("writes a chosen filter back to the address and drops it with ALL", () => {
    const { result } = renderHook(
      () => ({ list: useDocumentsList(), url: useLocation().search }),
      { wrapper: at("/warehouse?partner_id=p1") },
    );

    act(() => result.current.list.setTypeFilter("IN"));
    act(() => result.current.list.setStatusFilter("CONFIRMED"));
    expect(result.current.list.typeFilter).toBe("IN");
    expect(result.current.list.statusFilter).toBe("CONFIRMED");
    expect(result.current.url).toBe("?partner_id=p1&type=IN&status=CONFIRMED");

    act(() => result.current.list.setTypeFilter("ALL"));
    expect(result.current.list.typeFilter).toBe("ALL");
    expect(result.current.url).toBe("?partner_id=p1&status=CONFIRMED");
  });

  it("follows the address when it changes after the list is open", () => {
    // The module's own "Documents" tab links to the bare /warehouse while the
    // list is mounted: the screen has to follow, or a reload of that address
    // drops filters the screen still shows.
    const { result } = renderHook(
      () => ({ list: useDocumentsList(), navigate: useNavigate() }),
      {
        wrapper: at(
          "/warehouse?type=OUT&status=CONFIRMED&date_from=2026-10-14",
        ),
      },
    );
    expect(result.current.list.typeFilter).toBe("OUT");

    act(() => result.current.navigate("/warehouse"));
    expect(result.current.list.typeFilter).toBe("ALL");
    expect(result.current.list.statusFilter).toBe("ALL");
    expect(result.current.list.dateFrom).toBe("");

    act(() => result.current.navigate("/warehouse?type=IN&date_to=2026-10-17"));
    expect(result.current.list.typeFilter).toBe("IN");
    expect(result.current.list.dateTo).toBe("2026-10-17");
  });

  it("clears every address filter at once", () => {
    const { result } = renderHook(() => useDocumentsList(), {
      wrapper: at("/warehouse?type=OUT&status=CONFIRMED&partner_id=p1"),
    });

    act(() => result.current.clearFilters());

    expect(result.current.typeFilter).toBe("ALL");
    expect(result.current.statusFilter).toBe("ALL");
    expect(result.current.partnerId).toBeNull();
    expect(result.current.isNarrowed).toBe(false);
  });
});
