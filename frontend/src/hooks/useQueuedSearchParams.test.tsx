import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useQueuedSearchParams } from "./useQueuedSearchParams";
import { useOpenReplenishmentLink } from "@/modules/warehouse/hooks/useWorkItems";
import type { WorkItem } from "@/modules/warehouse/types";

const at =
  (address: string) =>
  ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[address]}>{children}</MemoryRouter>
  );

describe("useQueuedSearchParams", () => {
  it("keeps both writes of two hooks made before the screen renders", () => {
    const { result } = renderHook(
      () => ({
        first: useQueuedSearchParams()[1],
        second: useQueuedSearchParams()[1],
        search: useLocation().search,
      }),
      { wrapper: at("/list?keep=1&drop=1") },
    );

    act(() => {
      result.current.first((next) => next.set("sort", "name"));
      result.current.second((next) => next.delete("drop"));
    });

    expect(result.current.search).toBe("?keep=1&sort=name");
  });

  it("is not undone by a link the screen consumes in the same moment", async () => {
    const onOpen = vi.fn();
    const tasks = [
      { source_kind: "replenishment", source_id: "r1" },
    ] as unknown as WorkItem[];
    const { result } = renderHook(
      () => {
        const [, writeParams] = useQueuedSearchParams();
        useOpenReplenishmentLink(
          tasks,
          1,
          // Another write on the same screen, made as the task opens.
          (item) => {
            writeParams((next) => next.set("view", "mine"));
            onOpen(item);
          },
          vi.fn(),
        );
        return useLocation().search;
      },
      { wrapper: at("/todo?replenish=r1") },
    );

    await waitFor(() => expect(result.current).toBe("?view=mine"));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});
