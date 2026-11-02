import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { WorkItem } from "@/modules/warehouse/types";
import { useOpenReplenishmentLink } from "../useWorkItems";

const alert = {
  key: "replenishment:rule-7",
  source_kind: "replenishment",
  source_id: "rule-7",
} as WorkItem;

function setup(tasks: WorkItem[], total: number) {
  const onOpen = vi.fn();
  const onLoadAll = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={["/warehouse/todo?replenish=rule-7"]}>
      {children}
    </MemoryRouter>
  );
  renderHook(() => useOpenReplenishmentLink(tasks, total, onOpen, onLoadAll), {
    wrapper,
  });
  return { onOpen, onLoadAll };
}

describe("useOpenReplenishmentLink", () => {
  it("opens the task when it is among the loaded ones", () => {
    const { onOpen, onLoadAll } = setup([alert], 1);
    expect(onOpen).toHaveBeenCalledWith(alert);
    expect(onLoadAll).not.toHaveBeenCalled();
  });

  it("asks for the rest of the list when the task may lie past the loaded page", () => {
    const { onOpen, onLoadAll } = setup([], 136);
    expect(onOpen).not.toHaveBeenCalled();
    expect(onLoadAll).toHaveBeenCalledTimes(1);
  });

  it("waits quietly when the whole list is loaded and the task is not in it", () => {
    const { onOpen, onLoadAll } = setup([], 0);
    expect(onOpen).not.toHaveBeenCalled();
    expect(onLoadAll).not.toHaveBeenCalled();
  });
});
