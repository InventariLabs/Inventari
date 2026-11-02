import { beforeEach, describe, expect, it, vi } from "vitest";
import * as modulesCtx from "@/contexts/ModulesContext";
import { documentsApi } from "@/modules/warehouse/api/documents";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryWrapper } from "@/test/queryWrapper";
import {
  fetchDocumentsTodoCount,
  useDocumentsTodo,
} from "@/modules/warehouse/hooks/useDocumentsTodo";
import { todayIso } from "@/utils/formatters";

describe("the floor's queue", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("counts the tasks and the quarantine holds from the server's totals", async () => {
    const todo = vi.spyOn(documentsApi, "todo").mockResolvedValue({
      inbound: { items: [], total: 3 },
      outbound: { items: [], total: 4 },
      decisions: {
        backorders: { items: [], total: 2 },
        approvals: { items: [], total: 1 },
        quarantine: { items: [], total: 5 },
      },
      work_items: { items: [], total: 12 },
    });

    // The tasks already include the backorders and approvals; only the
    // quarantine holds are counted beside them.
    await expect(fetchDocumentsTodoCount()).resolves.toBe(17);
    expect(todo).toHaveBeenCalledWith({
      date_to: todayIso(),
      limit: 1,
    });
  });

  it("asks for the tasks it shows, narrowed on the server", async () => {
    const todo = vi.spyOn(documentsApi, "todo").mockResolvedValue({
      inbound: { items: [], total: 0 },
      outbound: { items: [], total: 0 },
      decisions: {
        backorders: { items: [], total: 0 },
        approvals: { items: [], total: 0 },
        quarantine: { items: [], total: 0 },
      },
      work_items: { items: [], total: 0 },
    });

    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["warehouse"],
      isModuleEnabled: () => true,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });

    const { result } = renderHook(
      () => useDocumentsTodo({ limit: 400, view: "mine" }),
      { wrapper: QueryWrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // The document lists keep the server's own page cap; the tasks get more.
    expect(todo).toHaveBeenCalledWith({
      date_to: todayIso(),
      limit: 200,
      work_limit: 400,
      view: "mine",
    });
  });
});
