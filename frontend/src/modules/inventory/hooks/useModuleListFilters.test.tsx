import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { useModuleListFilters } from "./useModuleListFilters";

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
};

const contributor = {
  key: "maker-has-bom",
  label: "maker:bomEntry.columnHeader",
  requiredModule: "maker",
  queryKey: ["test", "template-ids"] as const,
  fetchTemplateIds: vi.fn(async () => ["t1", "t2"]),
};

describe("module-contributed list filters", () => {
  beforeEach(() => {
    vi.spyOn(moduleRegistry, "getListFilterContributors").mockImplementation(
      (_table, enabled) => (enabled.includes("maker") ? [contributor] : []),
    );
    contributor.fetchTemplateIds.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("offers no chip when the contributing module is off", () => {
    const { result } = renderHook(
      () => useModuleListFilters("items", ["inventory"], [], vi.fn()),
      { wrapper },
    );
    expect(result.current.chips).toEqual([]);
    expect(result.current.templateIds).toBeUndefined();
  });

  it("offers the chip when the module is on, and fetches nothing until it is used", () => {
    const { result } = renderHook(
      () => useModuleListFilters("items", ["maker"], [], vi.fn()),
      { wrapper },
    );
    expect(result.current.chips.map((c) => c.key)).toEqual(["maker-has-bom"]);
    expect(result.current.chips[0].active).toBe(false);
    expect(contributor.fetchTemplateIds).not.toHaveBeenCalled();
  });

  it("narrows to the ids the module answers with once active", async () => {
    const { result } = renderHook(
      () =>
        useModuleListFilters("items", ["maker"], ["maker-has-bom"], vi.fn()),
      { wrapper },
    );
    await waitFor(() =>
      expect(result.current.templateIds).toEqual(["t1", "t2"]),
    );
    expect(result.current.chips[0].active).toBe(true);
  });

  it("empties the list when the module's set arrives empty, rather than showing everything", async () => {
    // Stable arrays, as the app passes them: a fresh `["maker"]` each render
    // would recompute the contributors and hide the stale memo.
    const enabled = ["maker"];
    const active = ["maker-has-bom"];
    contributor.fetchTemplateIds.mockResolvedValueOnce([]);
    const { result } = renderHook(
      () => useModuleListFilters("items", enabled, active, vi.fn()),
      { wrapper },
    );

    expect(result.current.templateIds).toBeUndefined();
    await waitFor(() => expect(result.current.templateIds).toEqual([]));
  });

  it("leaves the list alone while the answer is still loading", () => {
    const { result } = renderHook(
      () =>
        useModuleListFilters("items", ["maker"], ["maker-has-bom"], vi.fn()),
      { wrapper },
    );
    // An empty id list would match nothing and blank the page; `undefined`
    // means "no filter yet".
    expect(result.current.templateIds).toBeUndefined();
  });
});
