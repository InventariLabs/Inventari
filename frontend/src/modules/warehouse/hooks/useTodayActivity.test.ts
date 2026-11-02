import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryWrapper } from "@/test/queryWrapper";
import * as modulesCtx from "@/contexts/ModulesContext";
import { documentsApi } from "@/modules/warehouse/api/documents";
import {
  todayBounds,
  useTodayActivity,
} from "@/modules/warehouse/hooks/useTodayActivity";

const NOW = new Date(2026, 9, 20, 15, 30, 0);

function enableDocuments() {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["warehouse"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
}

describe("today's activity", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    enableDocuments();
  });

  it("runs from the reader's midnight to the next, whatever the server's zone", () => {
    const bounds = todayBounds(NOW);
    expect(bounds.from).toBe(
      new Date(NOW.getFullYear(), NOW.getMonth(), NOW.getDate()).toISOString(),
    );
    expect(bounds.to).toBe(
      new Date(
        NOW.getFullYear(),
        NOW.getMonth(),
        NOW.getDate() + 1,
      ).toISOString(),
    );
  });

  it("reads what was posted today, newest posting first", async () => {
    const list = vi
      .spyOn(documentsApi, "list")
      .mockResolvedValue({ items: [], total: 0 } as never);

    const { result } = renderHook(() => useTodayActivity(), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(list).toHaveBeenCalledWith({
      status: "COMPLETED",
      completed_from: todayBounds().from,
      completed_to: todayBounds().to,
      location_id: undefined,
      sort_by: "completed_at",
      sort_order: "desc",
      limit: 50,
    });
  });

  it("asks only for the chosen warehouse and the shelves under it", async () => {
    const list = vi
      .spyOn(documentsApi, "list")
      .mockResolvedValue({ items: [], total: 0 } as never);

    const { result } = renderHook(() => useTodayActivity("w-north"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(list).toHaveBeenCalledWith(
      expect.objectContaining({ location_id: "w-north" }),
    );
  });
});
